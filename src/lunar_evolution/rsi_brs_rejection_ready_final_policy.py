"""Import-time finite executable inventory of the dedicated final reader.

No filesystem observation, DTO serialization, configured clock or ownership
callback is invoked by this guard.  The enclosing owner policy must independently
hold the returned checker and final entry closures before an owner is captured.
"""

from __future__ import annotations

import _sqlite3
import builtins
import hashlib
import json
import math
import os
import sqlite3
import stat
import sys
import time
import types

from . import rsi_brs_rejection_ready_ack as ack_graph
from . import rsi_brs_rejection_ready_ledger as ledger
from . import rsi_brs_rejection_ready_locks as locks
from . import rsi_brs_rejection_ready_state as transport_state
from . import rsi_brs_rejection_ready_sync as sync
from . import rsi_learning as learning


def build_rejection_ready_final_guard(functions, namespace):
    """Hold declared code/closure/runtime now; never baseline during final reads."""
    kind, length, namespace_of, some, pairs = type, len, vars, any, zip
    plain_tuple, plain_dict, plain_str = tuple, dict, str
    function_type, module_type = types.FunctionType, types.ModuleType
    error_type, error_new = learning.RSILearningError, BaseException.__new__
    error_dict = namespace_of(BaseException)["__dict__"]
    dict_get, dict_set = types.GetSetDescriptorType.__get__, dict.__setitem__
    prefix, missing = "rsi_brs_rejection_ready_final_graph_drift", object()

    def fail():
        error = error_new(error_type, prefix)
        dict_set(dict_get(error_dict, error, error_type), "code", prefix)
        raise error

    def pack(function):
        if kind(function) is not function_type:
            fail()
        return (function, function.__code__, function.__globals__, function.__builtins__,
                function.__defaults__, function.__kwdefaults__,
                plain_tuple((function.__kwdefaults__ or {}).items()), function.__closure__,
                plain_tuple(cell.cell_contents for cell in function.__closure__ or ()),
                function.__dict__, plain_tuple(function.__dict__.items()),
                function.__annotations__, plain_tuple(function.__annotations__.items()),
                function.__name__, function.__qualname__, function.__module__, function.__doc__)

    ledger_namespace = namespace_of(ledger)
    ledger_functions = plain_tuple(value for value in ledger_namespace.values()
                                   if kind(value) is function_type and value.__globals__ is ledger_namespace)
    all_functions = (*functions, *ledger_functions, locks.assert_rejection_ready_locks,
                     sync.assert_ready_condition, *transport_state._STATE_FUNCTIONS,
                     ack_graph.assert_rejection_ready_ack_graph, ack_graph.assert_rejection_ready_ack,
                     ack_graph.build_rejection_ready_ack, learning.RSILearningError.__init__, fail)
    pins = plain_tuple(pack(function) for function in all_functions)
    modules = (builtins, hashlib, json, math, os, stat, sys, time, types, ledger, locks, sync,
               learning, sqlite3, _sqlite3, transport_state, ack_graph)
    registry = sys.modules
    module_pins = plain_tuple((module, namespace_of(module), module.__name__) for module in modules)
    own_aliases = plain_tuple(namespace.items())
    ledger_aliases = plain_tuple(ledger_namespace.items())
    builtin_namespace = namespace_of(builtins)
    builtin_names = ("type", "len", "vars", "id", "tuple", "dict", "str", "int", "bytes", "list",
                     "bool", "float", "any", "all", "zip", "sorted", "object", "min", "set",
                     "map", "sum", "range", "enumerate", "chr", "getattr", "isinstance",
                     "BaseException", "Exception", "ValueError", "TypeError", "OverflowError",
                     "UnicodeError", "FileNotFoundError", "OSError", "super")
    builtin_pins = plain_tuple((name, builtin_namespace[name]) for name in builtin_names)
    edges = plain_tuple((module, name, namespace_of(module)[name]) for module, names in (
        (os, ("open", "read", "close", "stat", "fstat", "listdir", "O_RDONLY", "O_DIRECTORY",
              "O_NOFOLLOW", "O_NONBLOCK", "O_CLOEXEC")),
        (stat, ("S_ISREG", "S_ISDIR", "S_IMODE")),
        (hashlib, ("sha256",)), (math, ("isfinite",)), (time, ("time", "monotonic")),
        (types, ("MemberDescriptorType", "GetSetDescriptorType", "MappingProxyType",
                 "FunctionType", "ModuleType")),
        (learning, ("RSILearningError",)),
        (locks, ("assert_rejection_ready_locks",)), (sync, ("assert_ready_condition",)),
        (transport_state, ("assert_selected_ready_inflight", "_STATE_FUNCTIONS")),
        (ack_graph, ("assert_rejection_ready_ack_graph", "assert_rejection_ready_ack",
                     "build_rejection_ready_ack")),
        (sqlite3, ("connect", "Connection", "Cursor", "Error", "DataError", "SQLITE_LIMIT_LENGTH")),
        (_sqlite3, ("connect", "Connection", "Cursor", "Error", "DataError", "SQLITE_LIMIT_LENGTH")),
    ) for name in names)
    digest_type = kind(hashlib.sha256())
    native_members = plain_tuple((declared, name, namespace_of(declared)[name])
                                for declared, names in (
        (types.MemberDescriptorType, ("__get__",)), (types.GetSetDescriptorType, ("__get__",)),
        (object, ("__getattribute__",)), (type, ("__getattribute__",)),
        (BaseException, ("__new__", "__dict__")), (dict, ("__setitem__", "get", "items")),
        (digest_type, ("update", "hexdigest")),
        (_sqlite3.Connection, ("execute", "close", "setlimit")),
        (_sqlite3.Cursor, ("__iter__", "__next__")),
    ) for name in names)
    error_members = plain_tuple(namespace_of(error_type).items())

    def guard():
        # All failure construction uses the original C allocator and native
        # descriptors, even if the application's error initializer changed.
        if (kind(namespace) is not plain_dict or length(namespace) > 16384
                or some(kind(name) is not plain_str for name in namespace)
                or some(namespace.get(name, missing) is not original for name, original in own_aliases)):
            fail()
        if (sys.modules is not registry or kind(registry) is not plain_dict
                or some(kind(name) is not plain_str for name in registry)):
            fail()
        for module, module_namespace, name in module_pins:
            if (kind(module) is not module_type or namespace_of(module) is not module_namespace
                    or registry.get(name, missing) is not module
                    or some(kind(key) is not plain_str for key in module_namespace)):
                fail()
        for module, name, original in edges:
            if namespace_of(module).get(name, missing) is not original:
                fail()
        if (length(ledger_namespace) != length(ledger_aliases)
                or some(ledger_namespace.get(name, missing) is not original for name, original in ledger_aliases)):
            fail()
        current_error_members = namespace_of(error_type)
        if (length(current_error_members) != length(error_members)
                or some(current_error_members.get(name, missing) is not original
                        for name, original in error_members)):
            fail()
        for declared, name, original in native_members:
            if namespace_of(declared).get(name, missing) is not original:
                fail()
        for name, original in builtin_pins:
            if builtin_namespace.get(name, missing) is not original:
                fail()
        for pin in pins:
            (function, code, domain, builtin_domain, defaults, kwdefaults, kwitems, closure, captures,
             attributes, attritems, annotations, annotationitems, name, qualname, module, doc) = pin
            if (kind(function) is not function_type or function.__code__ is not code
                    or function.__globals__ is not domain or function.__builtins__ is not builtin_domain
                    or function.__defaults__ is not defaults or function.__kwdefaults__ is not kwdefaults
                    or function.__closure__ is not closure or function.__dict__ is not attributes
                    or function.__annotations__ is not annotations):
                fail()
            for mapping, items in ((kwdefaults, kwitems), (attributes, attritems), (annotations, annotationitems)):
                if mapping is None:
                    continue
                if (kind(mapping) is not plain_dict or length(mapping) != length(items)
                        or some(kind(key) is not plain_str for key in mapping)
                        or some(mapping.get(key, missing) is not original for key, original in items)):
                    fail()
            for cell, original in pairs(closure or (), captures):
                try:
                    if cell.cell_contents is not original:
                        fail()
                except ValueError:
                    fail()
            for current, original in ((function.__name__, name), (function.__qualname__, qualname),
                                      (function.__module__, module), (function.__doc__, doc)):
                if kind(current) is not kind(original) or current != original:
                    fail()
            for name, original in builtin_pins:
                if domain.get(name, original) is not original or builtin_domain.get(name, missing) is not original:
                    fail()

    guard.__dict__["_fixed_helpers"] = (fail,)
    return guard


_FINAL_POLICY_FUNCTIONS = (build_rejection_ready_final_guard,)
