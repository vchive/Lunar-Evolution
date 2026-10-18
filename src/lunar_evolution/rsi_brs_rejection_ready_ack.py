"""Finite original ACK constructor and slot custody, without publication authority.

The enclosing owner policy must independently hold all three exported closures,
including their code and closure cells. This guard only checks its declared live
ACK graph. It does not inspect an owner, dequeue a request or publish an ACK.
"""

from __future__ import annotations

import builtins
import dataclasses
import re
import sys
import types

from . import rsi_learning as learning
from . import rsi_python_brs_admission as admission


def _build_guards():
    kind, length, namespace_of, some, pairs = type, len, vars, any, zip
    plain_dict, plain_tuple, plain_str, plain_set = dict, tuple, str, set
    function_type, module_type = types.FunctionType, types.ModuleType
    descriptor_type, mapping_type = types.MemberDescriptorType, types.MappingProxyType
    cell_type, pattern_type = types.CellType, re.Pattern
    # Refusals must not execute a changed application exception initializer.
    error_type, error_new = learning.RSILearningError, ValueError.__new__
    value_error, attribute_error = ValueError, AttributeError
    prefix = "rsi_brs_rejection_ready_ack_graph_drift"
    missing, max_keys = object(), 16384
    builtin_namespace, registry = namespace_of(builtins), sys.modules
    own_namespace = globals()
    ack_type, channel_type = admission.BRSAdmissionAck, admission.BRSAdmissionChannel
    names = ("run_id", "episode_id", "request_sha256", "record_sha256")
    constructor = namespace_of(ack_type)["__init__"]
    object_new = object.__new__
    identifier, digest = admission._identity, admission._sha
    slot_get = namespace_of(descriptor_type)["__get__"]
    slots = plain_tuple(namespace_of(ack_type)[name] for name in names)
    field_type = dataclasses.Field
    parameters = namespace_of(ack_type)["__dataclass_params__"]
    parameter_type = kind(parameters)
    field_slots = plain_tuple((name, namespace_of(field_type)[name])
                             for name in field_type.__slots__)
    parameter_slots = plain_tuple((name, namespace_of(parameter_type)[name])
                                 for name in parameter_type.__slots__)
    fields = namespace_of(ack_type)["__dataclass_fields__"]
    field_pins = plain_tuple((name, fields[name], plain_tuple(
        (label, descriptor, slot_get(descriptor, fields[name], field_type))
        for label, descriptor in field_slots)) for name in names)
    parameter_pins = plain_tuple((name, descriptor,
                                  slot_get(descriptor, parameters, parameter_type))
                                 for name, descriptor in parameter_slots)
    metadata_pins = plain_tuple((field, slot_get(namespace_of(field_type)["metadata"],
                                               field, field_type),
                                 plain_tuple(field.metadata.items()))
                                for _name, field, _values in field_pins)
    annotations = namespace_of(ack_type)["__annotations__"]
    annotation_items = plain_tuple(annotations.items())
    classes = (ack_type, admission.RSIPythonBRSAdmissionError, error_type,
               field_type, parameter_type)
    class_pins = plain_tuple((declaration, declaration.__bases__, declaration.__mro__,
                             plain_tuple(namespace_of(declaration).items()))
                            for declaration in classes)

    def pack(function):
        if kind(function) is not function_type:
            raise error_new(error_type, prefix)
        return (function, function.__code__, function.__globals__, function.__builtins__,
                function.__defaults__, function.__kwdefaults__,
                plain_tuple((function.__kwdefaults__ or {}).items()), function.__closure__,
                plain_tuple(cell.cell_contents for cell in (function.__closure__ or ())),
                function.__dict__, plain_tuple(function.__dict__.items()),
                function.__annotations__, plain_tuple(function.__annotations__.items()),
                function.__name__, function.__qualname__, function.__module__, function.__doc__)

    function_pins = plain_tuple(pack(function) for function in (
        constructor, namespace_of(ack_type)["__post_init__"], admission._identity,
        admission._sha, admission._fail,
        namespace_of(admission.RSIPythonBRSAdmissionError)["__init__"],
        namespace_of(error_type)["__init__"], namespace_of(channel_type)["request"],
    ))
    modules = plain_tuple((module, namespace_of(module)) for module in (
        admission, learning, builtins, dataclasses, re, sys, types))
    registered = plain_tuple((module.__name__, module) for module, _namespace in modules)
    edges = (
        (admission, "BRSAdmissionAck", ack_type),
        (admission, "BRSAdmissionChannel", channel_type),
        (admission, "RSIPythonBRSAdmissionError", admission.RSIPythonBRSAdmissionError),
        (admission, "RSILearningError", error_type),
        (learning, "RSILearningError", error_type),
        (admission, "_identity", admission._identity),
        (admission, "_sha", admission._sha), (admission, "_fail", admission._fail),
        (admission, "_ID", admission._ID), (admission, "_SHA", admission._SHA),
        (dataclasses, "Field", field_type), (re, "Pattern", pattern_type),
        (types, "FunctionType", function_type), (types, "ModuleType", module_type),
        (types, "MemberDescriptorType", descriptor_type),
        (types, "MappingProxyType", mapping_type), (types, "CellType", cell_type),
    )
    native_pins = (
        (object, "__new__", object.__new__), (object, "__getattribute__", object.__getattribute__),
        (object, "__setattr__", object.__setattr__), (type, "__call__", type.__call__),
        (type, "__getattribute__", type.__getattribute__),
        (ValueError, "__new__", ValueError.__new__),
        (BaseException, "__init__", BaseException.__init__),
        (descriptor_type, "__get__", slot_get),
        (descriptor_type, "__set__", namespace_of(descriptor_type)["__set__"]),
        (cell_type, "cell_contents", namespace_of(cell_type)["cell_contents"]),
        (pattern_type, "fullmatch", namespace_of(pattern_type)["fullmatch"]),
        (pattern_type, "pattern", namespace_of(pattern_type)["pattern"]),
        (pattern_type, "flags", namespace_of(pattern_type)["flags"]),
    )
    builtin_names = ("type", "len", "vars", "any", "zip", "dict", "tuple", "str", "set",
                     "object", "super", "ValueError", "BaseException", "AttributeError",
                     "isinstance", "callable", "bool", "bytes", "int", "float")
    builtin_bindings = plain_tuple((name, builtin_namespace[name]) for name in builtin_names)
    namespaces = plain_tuple((namespace, namespace.get("__builtins__"), function.__builtins__)
                             for function, _code, namespace, *_rest in function_pins)
    original_request = namespace_of(channel_type)["request"]
    request_bases, request_mro = channel_type.__bases__, channel_type.__mro__
    own_aliases = ()

    def assert_graph():
        # All bootstrap operations are captured native primitives. No changed
        # class getter, helper, regex or error initializer runs to detect drift.
        if (length(own_namespace) > max_keys
                or some(kind(key) is not plain_str for key in own_namespace)):
            raise error_new(error_type, prefix)
        for name, original in own_aliases:
            if own_namespace.get(name, missing) is not original:
                raise error_new(error_type, prefix)
        for module, namespace in modules:
            if (kind(module) is not module_type or namespace_of(module) is not namespace
                    or length(namespace) > max_keys
                    or some(kind(key) is not plain_str for key in namespace)):
                raise error_new(error_type, prefix)
        if (namespace_of(sys).get("modules", missing) is not registry
                or kind(registry) is not plain_dict or length(registry) > max_keys
                or some(kind(key) is not plain_str for key in registry)):
            raise error_new(error_type, prefix)
        for name, module in registered:
            if registry.get(name, missing) is not module:
                raise error_new(error_type, prefix)
        for module, name, original in edges:
            if namespace_of(module).get(name, missing) is not original:
                raise error_new(error_type, prefix)
        for declaration, name, original in native_pins:
            if namespace_of(declaration).get(name, missing) is not original:
                raise error_new(error_type, prefix)
        for name, original in builtin_bindings:
            if builtin_namespace.get(name, missing) is not original:
                raise error_new(error_type, prefix)
        for namespace, original, domain in namespaces:
            if namespace.get("__builtins__", missing) is not original:
                raise error_new(error_type, prefix)
            if (kind(domain) is not plain_dict or length(domain) > max_keys
                    or some(kind(key) is not plain_str for key in domain)):
                raise error_new(error_type, prefix)
            for name, value in builtin_bindings:
                if (namespace.get(name, value) is not value
                        or domain.get(name, missing) is not value):
                    raise error_new(error_type, prefix)
        for declaration, bases, mro, members in class_pins:
            if (kind(declaration) is not kind or declaration.__bases__ is not bases
                    or declaration.__mro__ is not mro):
                raise error_new(error_type, prefix)
            current = namespace_of(declaration)
            if (length(current) != length(members)
                    or some(kind(key) is not plain_str for key in current)):
                raise error_new(error_type, prefix)
            for name, original in members:
                if current.get(name, missing) is not original:
                    raise error_new(error_type, prefix)
        if (channel_type.__bases__ is not request_bases or channel_type.__mro__ is not request_mro
                or namespace_of(channel_type).get("request", missing) is not original_request):
            raise error_new(error_type, prefix)
        if (kind(fields) is not plain_dict or length(fields) != 4
                or some(kind(key) is not plain_str for key in fields)
                or plain_set(fields) != plain_set(names)):
            raise error_new(error_type, prefix)
        for name, field, values in field_pins:
            if fields.get(name, missing) is not field or kind(field) is not field_type:
                raise error_new(error_type, prefix)
            for _label, descriptor, original in values:
                if slot_get(descriptor, field, field_type) is not original:
                    raise error_new(error_type, prefix)
        for _name, descriptor, original in parameter_pins:
            if slot_get(descriptor, parameters, parameter_type) is not original:
                raise error_new(error_type, prefix)
        for _field, metadata, saved in metadata_pins:
            if (kind(metadata) is not mapping_type or length(metadata) != length(saved)
                    or some(kind(key) is not plain_str for key in metadata)):
                raise error_new(error_type, prefix)
            for name, original in saved:
                if metadata.get(name, missing) is not original:
                    raise error_new(error_type, prefix)
        if (kind(annotations) is not plain_dict or length(annotations) != length(annotation_items)
                or some(kind(key) is not plain_str for key in annotations)):
            raise error_new(error_type, prefix)
        for name, original in annotation_items:
            if annotations.get(name, missing) is not original:
                raise error_new(error_type, prefix)
        for pin in function_pins:
            (function, code, namespace, domain, defaults, kwdefaults, kwitems,
             closure, captures, attributes, attritems, labels, labelitems,
             name, qualname, module, doc) = pin
            if (kind(function) is not function_type or function.__code__ is not code
                    or function.__globals__ is not namespace or function.__builtins__ is not domain
                    or function.__defaults__ is not defaults or function.__kwdefaults__ is not kwdefaults
                    or function.__closure__ is not closure or function.__dict__ is not attributes
                    or function.__annotations__ is not labels):
                raise error_new(error_type, prefix)
            for mapping, saved in ((kwdefaults, kwitems), (attributes, attritems),
                                   (labels, labelitems)):
                if mapping is None:
                    continue
                if (kind(mapping) is not plain_dict or length(mapping) != length(saved)
                        or some(kind(key) is not plain_str for key in mapping)):
                    raise error_new(error_type, prefix)
                for key, original in saved:
                    if mapping.get(key, missing) is not original:
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

    guard_pin = None

    def build(fields):
        # Independently check the held graph entry before executing its code.
        (function, code, namespace, domain, defaults, kwdefaults, kwitems,
         closure, captures, attributes, attritems, labels, labelitems,
         name, qualname, module, doc) = guard_pin
        if (function is not assert_graph or kind(function) is not function_type
                or function.__code__ is not code or function.__globals__ is not namespace
                or function.__builtins__ is not domain or function.__defaults__ is not defaults
                or function.__kwdefaults__ is not kwdefaults or function.__closure__ is not closure
                or function.__dict__ is not attributes or function.__annotations__ is not labels):
            raise error_new(error_type, prefix)
        for mapping, saved in ((kwdefaults, kwitems), (attributes, attritems), (labels, labelitems)):
            if mapping is None:
                continue
            if (kind(mapping) is not plain_dict or length(mapping) != length(saved)
                    or some(kind(key) is not plain_str for key in mapping)):
                raise error_new(error_type, prefix)
            for key, original in saved:
                if mapping.get(key, missing) is not original:
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
        assert_graph()
        if (kind(fields) is not plain_tuple or length(fields) != 4
                or some(kind(value) is not plain_str for value in fields)):
            raise error_new(error_type, "rsi_brs_rejection_ready_ack_fields_invalid")
        # Use the held original type only after its complete constructor graph
        # has passed; no DTO serializer or owner permission participates.
        ack = object_new(ack_type)
        constructor(ack, *fields)
        for descriptor, original in pairs(slots, fields):
            value = slot_get(descriptor, ack, ack_type)
            if kind(value) is not plain_str or value != original:
                raise error_new(error_type, "rsi_brs_rejection_ready_ack_mismatch")
        return ack

    def check(ack, fields):
        # Independently check the held graph entry before executing its code.
        (function, code, namespace, domain, defaults, kwdefaults, kwitems,
         closure, captures, attributes, attritems, labels, labelitems,
         name, qualname, module, doc) = guard_pin
        if (function is not assert_graph or kind(function) is not function_type
                or function.__code__ is not code or function.__globals__ is not namespace
                or function.__builtins__ is not domain or function.__defaults__ is not defaults
                or function.__kwdefaults__ is not kwdefaults or function.__closure__ is not closure
                or function.__dict__ is not attributes or function.__annotations__ is not labels):
            raise error_new(error_type, prefix)
        for mapping, saved in ((kwdefaults, kwitems), (attributes, attritems), (labels, labelitems)):
            if mapping is None:
                continue
            if (kind(mapping) is not plain_dict or length(mapping) != length(saved)
                    or some(kind(key) is not plain_str for key in mapping)):
                raise error_new(error_type, prefix)
            for key, original in saved:
                if mapping.get(key, missing) is not original:
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
        assert_graph()
        if (kind(fields) is not plain_tuple or length(fields) != 4
                or some(kind(value) is not plain_str for value in fields)
                or kind(ack) is not ack_type):
            raise error_new(error_type, "rsi_brs_rejection_ready_ack_fields_invalid")
        for descriptor, original in pairs(slots, fields):
            try:
                value = slot_get(descriptor, ack, ack_type)
            except attribute_error:
                raise error_new(error_type, "rsi_brs_rejection_ready_ack_mismatch") from None
            if kind(value) is not plain_str or value != original:
                raise error_new(error_type, "rsi_brs_rejection_ready_ack_mismatch")
        identifier(fields[0])
        identifier(fields[1])
        digest(fields[2])
        digest(fields[3])

    assert_graph.__name__ = "assert_rejection_ready_ack_graph"
    build.__name__ = "build_rejection_ready_ack"
    check.__name__ = "assert_rejection_ready_ack"
    own_aliases = plain_tuple((name, own_namespace[name]) for name in (
        "builtins", "dataclasses", "re", "sys", "types", "learning", "admission", "_build_guards")) + (
        ("assert_rejection_ready_ack_graph", assert_graph),
        ("build_rejection_ready_ack", build), ("assert_rejection_ready_ack", check))
    guard_pin = pack(assert_graph)
    return assert_graph, build, check


(assert_rejection_ready_ack_graph, build_rejection_ready_ack,
 assert_rejection_ready_ack) = _build_guards()
