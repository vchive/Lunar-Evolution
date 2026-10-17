"""Finite Condition custody checks; these comparison capsules grant no authority.

No operation here acquires/releases a lock, waits, notifies, or invokes a waiter.
The enclosing reader must independently retain these entry points and its own
observation context. This is not a guard for the complete final ACK reader.
"""

from __future__ import annotations

import _thread
import builtins
import collections
import itertools
import sys
import threading
import types

from .rsi_learning import RSILearningError

_MAX_WAITERS = 4096


def _build_guards():
    # Retain real imports, C descriptors and builtin operations independently of
    # the application aliases that are checked below on every entry.
    kind = type
    length = len
    namespace_of = vars
    identity = id
    pairs = zip
    some = any
    value_error = ValueError
    runtime_error = RuntimeError
    system_module = sys
    builtin_namespace = vars(builtins)
    plain_tuple = tuple
    plain_dict = dict
    plain_str = str
    plain_set = set
    function_type = types.FunctionType
    module_type = types.ModuleType
    bound_type = types.BuiltinMethodType
    condition_type = threading.Condition
    lock_type = _thread.RLock
    waiter_type = _thread.LockType
    deque_type = collections.deque
    error_type = RSILearningError
    condition_bases = condition_type.__bases__
    condition_mro = condition_type.__mro__
    condition_names = plain_tuple(namespace_of(condition_type))
    condition_members = plain_tuple(namespace_of(condition_type).items())
    operation_names = ("acquire", "release", "_release_save", "_acquire_restore", "_is_owned")
    instance_names = ("_lock", *operation_names, "_waiters")
    lock_descriptors = plain_tuple((name, namespace_of(lock_type)[name]) for name in (
        *operation_names, "__enter__", "__exit__"))
    waiter_descriptors = plain_tuple((name, namespace_of(waiter_type)[name])
                                     for name in ("acquire", "release"))
    max_waiters = _MAX_WAITERS
    max_namespace_keys = 16384
    prefix = "rsi_brs_rejection_ready_sync_"

    def pack(function):
        return (function, function.__code__, function.__globals__, function.__defaults__,
                function.__kwdefaults__, plain_tuple((function.__kwdefaults__ or {}).items()),
                function.__closure__, plain_tuple(cell.cell_contents
                                                  for cell in (function.__closure__ or ())),
                function.__dict__, plain_tuple(function.__dict__.items()),
                function.__annotations__, plain_tuple(function.__annotations__.items()),
                function.__name__, function.__qualname__, function.__module__, function.__doc__)

    def shape(condition):
        if kind(condition) is not condition_type:
            raise error_type(prefix + "condition_type")
        attributes = namespace_of(condition)
        if (kind(attributes) is not plain_dict or length(attributes) != length(instance_names)
                or some(kind(key) is not plain_str for key in attributes)):
            raise error_type(prefix + "instance_shape")
        if plain_set(attributes) != plain_set(instance_names):
            raise error_type(prefix + "instance_shape")
        lock = attributes["_lock"]
        waiters = attributes["_waiters"]
        if kind(lock) is not lock_type or kind(waiters) is not deque_type:
            raise error_type(prefix + "native_state")
        if waiters.maxlen is not None or length(waiters) > max_waiters:
            raise error_type(prefix + "waiter_domain")
        seen = plain_set()
        try:
            for waiter in waiters:
                if kind(waiter) is not waiter_type or identity(waiter) in seen:
                    raise error_type(prefix + "waiter_domain")
                seen.add(identity(waiter))
        except runtime_error:
            raise error_type(prefix + "waiter_domain") from None
        operations = []
        for name in operation_names:
            operation = attributes[name]
            if (kind(operation) is not bound_type or operation.__self__ is not lock
                    or kind(operation.__name__) is not plain_str or operation.__name__ != name
                    or operation.__qualname__ != "RLock." + name):
                raise error_type(prefix + "native_operation")
            operations.append(operation)
        return (condition, lock, waiters, *operations)

    modules = plain_tuple((module, namespace_of(module)) for module in (
        _thread, builtins, collections, itertools, sys, threading, types))
    builtin_names = ("type", "len", "vars", "id", "zip", "tuple", "dict", "str", "set", "any",
                     "AttributeError", "RuntimeError", "ValueError")
    builtin_bindings = plain_tuple((name, namespace_of(builtins)[name]) for name in builtin_names)
    edges = (
        (_thread, "RLock", lock_type), (_thread, "LockType", waiter_type),
        (_thread, "allocate_lock", _thread.allocate_lock),
        (collections, "deque", deque_type), (itertools, "islice", itertools.islice),
        (threading, "Condition", condition_type), (threading, "RLock", threading.RLock),
        (threading, "_CRLock", lock_type), (threading, "_PyRLock", threading._PyRLock),
        (threading, "_allocate_lock", _thread.allocate_lock),
        (threading, "_deque", deque_type), (threading, "_islice", itertools.islice),
        (types, "FunctionType", function_type), (types, "ModuleType", module_type),
        (types, "BuiltinMethodType", bound_type),
    )
    registered = plain_tuple((module.__name__, module) for module, _namespace in modules)
    registry = sys.modules
    threading_namespace = namespace_of(threading)
    original_builtins = threading_namespace["__builtins__"]
    function_pins = plain_tuple(pack(namespace_of(condition_type)[name]) for name in (
        "__init__", "__enter__", "__exit__", "wait", "notify", "notify_all",
        "_release_save", "_acquire_restore", "_is_owned")) + (pack(threading.RLock), pack(shape))
    own_namespace = globals()
    own_aliases = ()

    def runtime():
        if (length(own_namespace) > max_namespace_keys
                or some(kind(key) is not plain_str for key in own_namespace)
                or some(own_namespace.get(name) is not original for name, original in own_aliases)):
            raise error_type(prefix + "guard_alias")
        for module, namespace in modules:
            if kind(module) is not module_type or namespace_of(module) is not namespace:
                raise error_type(prefix + "module_drift")
            if (length(namespace) > max_namespace_keys
                    or some(kind(key) is not plain_str for key in namespace)):
                raise error_type(prefix + "module_keys")
        if kind(system_module.modules) is not plain_dict or system_module.modules is not registry:
            raise error_type(prefix + "module_registry")
        if (length(registry) > max_namespace_keys
                or some(kind(key) is not plain_str for key in registry)):
            raise error_type(prefix + "module_registry")
        for name, module in registered:
            if registry.get(name) is not module:
                raise error_type(prefix + "module_registry")
        for owner, name, original in edges:
            if namespace_of(owner).get(name) is not original:
                raise error_type(prefix + "alias_drift")
        for name, original in builtin_bindings:
            if builtin_namespace.get(name) is not original:
                raise error_type(prefix + "builtin_drift")
        # LOAD_GLOBAL can find a newly added threading global before builtins.
        if threading_namespace.get("__builtins__") is not original_builtins:
            raise error_type(prefix + "builtin_drift")
        if kind(original_builtins) is not plain_dict:
            raise error_type(prefix + "builtin_drift")
        if (length(original_builtins) > max_namespace_keys
                or some(kind(key) is not plain_str for key in original_builtins)):
            raise error_type(prefix + "builtin_drift")
        for name, original in builtin_bindings:
            if (threading_namespace.get(name, original) is not original
                    or original_builtins.get(name) is not original):
                raise error_type(prefix + "builtin_drift")
        if (condition_type.__bases__ is not condition_bases
                or condition_type.__mro__ is not condition_mro):
            raise error_type(prefix + "class_drift")
        current = namespace_of(condition_type)
        if (length(current) != length(condition_names)
                or some(kind(key) is not plain_str for key in current)
                or plain_set(current) != plain_set(condition_names)):
            raise error_type(prefix + "class_drift")
        for name, original in condition_members:
            if current[name] is not original:
                raise error_type(prefix + "class_drift")
        for owner, descriptors in ((lock_type, lock_descriptors),
                                   (waiter_type, waiter_descriptors)):
            for name, original in descriptors:
                if namespace_of(owner).get(name) is not original:
                    raise error_type(prefix + "native_descriptor")
        for pin in function_pins:
            (function, code, namespace, defaults, kwdefaults, kwitems, closure, captures,
             attributes, attritems, annotations, annotationitems, name, qualname, module, doc) = pin
            if (kind(function) is not function_type or function.__code__ is not code
                    or function.__globals__ is not namespace or function.__defaults__ is not defaults
                    or function.__kwdefaults__ is not kwdefaults or function.__closure__ is not closure
                    or function.__dict__ is not attributes or function.__annotations__ is not annotations):
                raise error_type(prefix + "function_drift")
            for mapping, entries in ((kwdefaults, kwitems), (attributes, attritems),
                                     (annotations, annotationitems)):
                if mapping is None:
                    continue
                if (kind(mapping) is not plain_dict or length(mapping) != length(entries)
                        or some(kind(key) is not plain_str for key in mapping)
                        or plain_set(mapping) != {key for key, _value in entries}):
                    raise error_type(prefix + "function_drift")
                for key, value in entries:
                    if mapping.get(key) is not value:
                        raise error_type(prefix + "function_drift")
            for cell, value in pairs(closure or (), captures):
                try:
                    if cell.cell_contents is not value:
                        raise error_type(prefix + "function_drift")
                except value_error:
                    raise error_type(prefix + "function_drift") from None
            for value, original in ((function.__name__, name), (function.__qualname__, qualname),
                                    (function.__module__, module), (function.__doc__, doc)):
                if kind(value) is not kind(original) or value != original:
                    raise error_type(prefix + "function_drift")

    runtime_pin = None

    def capture(condition):
        # Independently check the held checker before executing its Python code.
        (function, code, namespace, defaults, kwdefaults, _kwitems, closure, captures,
         attributes, attritems, annotations, annotationitems, name, qualname, module, doc) = runtime_pin
        if (function is not runtime or kind(function) is not function_type
                or function.__code__ is not code or function.__globals__ is not namespace
                or function.__defaults__ is not defaults or function.__kwdefaults__ is not kwdefaults
                or function.__closure__ is not closure or function.__dict__ is not attributes
                or function.__annotations__ is not annotations):
            raise error_type(prefix + "checker_drift")
        for mapping, entries in ((attributes, attritems), (annotations, annotationitems)):
            if (kind(mapping) is not plain_dict or length(mapping) != length(entries)
                    or some(kind(key) is not plain_str for key in mapping)
                    or plain_set(mapping) != {key for key, _value in entries}
                    or some(mapping.get(key) is not value for key, value in entries)):
                raise error_type(prefix + "checker_drift")
        for cell, value in pairs(closure or (), captures):
            try:
                if cell.cell_contents is not value:
                    raise error_type(prefix + "checker_drift")
            except value_error:
                raise error_type(prefix + "checker_drift") from None
        for value, original in ((function.__name__, name), (function.__qualname__, qualname),
                                (function.__module__, module), (function.__doc__, doc)):
            if kind(value) is not kind(original) or value != original:
                raise error_type(prefix + "checker_drift")
        runtime()
        return shape(condition)

    def compare(condition, snapshot):
        # Keep this bootstrap independent of the checker whose code is about to run.
        (function, code, namespace, defaults, kwdefaults, _kwitems, closure, captures,
         attributes, attritems, annotations, annotationitems, name, qualname, module, doc) = runtime_pin
        if (function is not runtime or kind(function) is not function_type
                or function.__code__ is not code or function.__globals__ is not namespace
                or function.__defaults__ is not defaults or function.__kwdefaults__ is not kwdefaults
                or function.__closure__ is not closure or function.__dict__ is not attributes
                or function.__annotations__ is not annotations):
            raise error_type(prefix + "checker_drift")
        for mapping, entries in ((attributes, attritems), (annotations, annotationitems)):
            if (kind(mapping) is not plain_dict or length(mapping) != length(entries)
                    or some(kind(key) is not plain_str for key in mapping)
                    or plain_set(mapping) != {key for key, _value in entries}
                    or some(mapping.get(key) is not value for key, value in entries)):
                raise error_type(prefix + "checker_drift")
        for cell, value in pairs(closure or (), captures):
            try:
                if cell.cell_contents is not value:
                    raise error_type(prefix + "checker_drift")
            except value_error:
                raise error_type(prefix + "checker_drift") from None
        for value, original in ((function.__name__, name), (function.__qualname__, qualname),
                                (function.__module__, module), (function.__doc__, doc)):
            if kind(value) is not kind(original) or value != original:
                raise error_type(prefix + "checker_drift")
        runtime()
        if kind(snapshot) is not plain_tuple or length(snapshot) != 8:
            raise error_type(prefix + "snapshot_shape")
        current = shape(condition)
        if some(value is not original for value, original in pairs(current, snapshot)):
            raise error_type(prefix + "custody_drift")

    own_aliases = plain_tuple((name, own_namespace[name]) for name in (
        "_thread", "builtins", "collections", "itertools", "sys", "threading", "types",
        "RSILearningError", "_MAX_WAITERS", "_build_guards")) + (
            ("capture_ready_condition", capture), ("assert_ready_condition", compare))
    runtime_pin = pack(runtime)
    capture.__name__ = "capture_ready_condition"
    compare.__name__ = "assert_ready_condition"
    return capture, compare


capture_ready_condition, assert_ready_condition = _build_guards()
