"""Finite live dependencies of original-owner pre-arm capture, without ACK authority.

The enclosing BRS policy independently holds this entry point and its source. This
projection observes the declared capture/reference/read-only helpers; it does not
call them or validate an owner. Complete final ACK physical/context custody and
stdlib cache state remain outside this pre-arm projection.
"""

from __future__ import annotations

import _sqlite3
import builtins
import hashlib
import json
import sqlite3
import sys
import types
import urllib.parse
from pathlib import Path

from . import rsi_brs_rejection_ready_ledger as ledger
from . import rsi_brs_rejection_ready_owner as owner
from . import rsi_brs_rejection_ready_reference as reference
from . import rsi_brs_rejection_ready_sync as sync
from .rsi_learning import RSILearningError


def _build_policy():
    kind, length, namespace_of, some = type, len, vars, any
    plain_dict, plain_str, plain_tuple, plain_set = dict, str, tuple, set
    pairs = zip
    function_type, module_type = types.FunctionType, types.ModuleType
    value_error, error_type = ValueError, RSILearningError
    registry, own_namespace, sys_namespace = sys.modules, globals(), vars(sys)
    prefix = "rsi_brs_rejection_ready_capture_policy_drift"
    max_keys = 16384
    function_names = (
        (owner, ("_fail", "_owner", "_custody", "_assert_custody", "_domain", "_payload",
                 "_empty", "_check_original", "retain_rejection_ready_capture")),
        (reference, ("_fail", "_digest", "_identifier", "_shadows", "_capture", "_check",
                     "validate_existing_rejection_reference")),
        (ledger, ("_fail", "_path", "_identifier", "_domain", "_row_size", "_schema_size",
                  "_snapshot_shape", "_read", "read_rejection_ready_rows",
                  "assert_rejection_ready_rows")),
        (sync, ("capture_ready_condition", "assert_ready_condition")),
    )

    def pack(module, name, function):
        if kind(function) is not function_type or function.__globals__ is not namespace_of(module):
            raise error_type(prefix)
        return (module, name, function, function.__code__, function.__globals__,
                function.__defaults__, function.__kwdefaults__,
                plain_tuple((function.__kwdefaults__ or {}).items()), function.__closure__,
                plain_tuple(cell.cell_contents for cell in (function.__closure__ or ())),
                function.__dict__, plain_tuple(function.__dict__.items()),
                function.__annotations__, plain_tuple(function.__annotations__.items()),
                function.__name__, function.__qualname__, function.__module__, function.__doc__)

    pins = [pack(module, name, namespace_of(module)[name])
            for module, names in function_names for name in names]
    parse = urllib.parse
    # These are explicit known quote edges, not a recursively discovered graph.
    for module, names in ((parse, ("quote", "quote_from_bytes")),
                          (json, ("loads", "dumps"))):
        pins.extend(pack(module, name, namespace_of(module)[name]) for name in names)
    factory = parse._byte_quoter_factory
    wrapped = factory.__wrapped__
    pins.append(pack(parse, "_byte_quoter_factory.__wrapped__", wrapped))
    quoter = parse._Quoter
    quoter_members = plain_tuple(namespace_of(quoter).items())
    quoter_bases, quoter_mro = quoter.__bases__, quoter.__mro__
    for name in ("__init__", "__missing__"):
        function = namespace_of(quoter)[name]
        # Class functions still resolve their globals in urllib.parse.
        pins.append(pack(parse, "_Quoter." + name, function))
    # Shared canonical serializer aliases are executable Python dependencies too.
    serializer = owner.canonical_json
    serializer_module = registry[serializer.__module__]
    pins.append(pack(serializer_module, "canonical_json", serializer))
    pins = plain_tuple(pins)

    modules = (owner, reference, ledger, sync)
    namespaces = plain_tuple((module, namespace_of(module),
                              plain_tuple(namespace_of(module).items())) for module in modules)
    runtime_modules = plain_tuple((module, namespace_of(module)) for module in (
        _sqlite3, sqlite3, parse, json, hashlib, builtins, types, sys, serializer_module))
    registered = plain_tuple((module.__name__, module) for module in (*modules,
                             *(module for module, _namespace in runtime_modules)))
    missing = object()
    connection_type, cursor_type = _sqlite3.Connection, _sqlite3.Cursor
    edges = (
        (ledger, "sqlite3", sqlite3), (ledger, "quote", parse.quote),
        (sqlite3, "connect", _sqlite3.connect), (_sqlite3, "connect", _sqlite3.connect),
        (sqlite3, "Connection", connection_type), (_sqlite3, "Connection", connection_type),
        (sqlite3, "Cursor", cursor_type), (_sqlite3, "Cursor", cursor_type),
        (sqlite3, "Error", _sqlite3.Error), (sqlite3, "DataError", _sqlite3.DataError),
        (_sqlite3, "Error", _sqlite3.Error), (_sqlite3, "DataError", _sqlite3.DataError),
        (sqlite3, "SQLITE_LIMIT_LENGTH", sqlite3.SQLITE_LIMIT_LENGTH),
        (parse, "quote", parse.quote), (parse, "quote_from_bytes", parse.quote_from_bytes),
        (parse, "_byte_quoter_factory", factory), (parse, "_Quoter", quoter),
        (parse, "_ALWAYS_SAFE", parse._ALWAYS_SAFE),
        (parse, "_ALWAYS_SAFE_BYTES", parse._ALWAYS_SAFE_BYTES),
        (hashlib, "sha256", hashlib.sha256), (json, "loads", json.loads),
        (json, "dumps", json.dumps),
        (serializer_module, "canonical_json", serializer),
    )
    sqlite_descriptors = plain_tuple((name, namespace_of(connection_type)[name]) for name in (
        "setlimit", "execute", "close")) + plain_tuple(
            ("cursor." + name, namespace_of(cursor_type)[name])
            for name in ("__iter__", "__next__"))
    builtin_namespace = namespace_of(builtins)
    builtin_names = ("type", "len", "vars", "any", "dict", "str", "tuple", "set", "zip",
                     "sorted", "bytes", "bytearray", "isinstance", "chr", "getattr", "range",
                     "enumerate", "staticmethod", "classmethod", "property",
                     "int", "float", "bool", "map", "sum", "all", "object",
                     "ValueError", "TypeError", "AttributeError", "RuntimeError", "Exception",
                     "BaseException", "KeyError", "UnicodeError", "OSError")
    builtin_bindings = plain_tuple((name, builtin_namespace[name]) for name in builtin_names)
    # LOAD_GLOBAL first consults a function's module, then its held builtin map.
    builtin_domains = []
    for _module, _name, function, *_rest in pins:
        namespace = function.__globals__
        domain = namespace.get("__builtins__")
        if kind(domain) is module_type:
            domain = namespace_of(domain)
        if kind(domain) is not plain_dict:
            raise error_type(prefix)
        builtin_domains.append((namespace, namespace.get("__builtins__"), domain))
    builtin_domains = plain_tuple(builtin_domains)
    method = owner.retain_rejection_ready_capture
    condition_assert = sync.assert_ready_condition
    publication_name = owner.__package__ + ".rsi_brs_publication_lineage"
    sources = {module.__name__.rsplit(".", 1)[-1]: hashlib.sha256(
        Path(module.__file__).read_bytes()).hexdigest() for module in modules}
    projection = {"protocol": "lunar-rsi-brs-rejection-ready-capture-policy-v1",
                  "sources": sources,
                  "functions": [[module.__name__, list(names)] for module, names in function_names],
                  "ledger_limits": [ledger._MAX_ROWS, ledger._MAX_IDS, ledger._MAX_ROW_BYTES,
                                    ledger._MAX_BYTES],
                  "scope": "read-only-pre-arm; no-owner-permit-or-ACK"}
    digest = hashlib.sha256(json.dumps(projection, sort_keys=True,
                                      separators=(",", ":")).encode()).hexdigest()
    protocol = projection["protocol"]
    own_aliases = plain_tuple(own_namespace.items())

    def project():
        # These entry-point operations use held primitives before inspecting any
        # live alias. The enclosing BRS policy independently pins this function.
        if (length(own_namespace) > max_keys
                or some(kind(key) is not plain_str for key in own_namespace)):
            raise error_type(prefix)
        for name, original in own_aliases:
            if own_namespace.get(name, missing) is not original:
                raise error_type(prefix)
        if (length(sys_namespace) > max_keys
                or some(kind(key) is not plain_str for key in sys_namespace)
                or sys_namespace.get("modules", missing) is not registry):
            raise error_type(prefix)
        if length(registry) > max_keys or some(kind(key) is not plain_str for key in registry):
            raise error_type(prefix)
        for name, module in registered:
            if registry.get(name, missing) is not module:
                raise error_type(prefix)
        for module, namespace, saved in namespaces:
            if kind(module) is not module_type or namespace_of(module) is not namespace:
                raise error_type(prefix)
            if (length(namespace) != length(saved)
                    or some(kind(key) is not plain_str for key in namespace)
                    or plain_set(namespace) != {name for name, _value in saved}):
                raise error_type(prefix)
            for name, original in saved:
                if namespace.get(name, missing) is not original:
                    raise error_type(prefix)
        for module, namespace in runtime_modules:
            if (kind(module) is not module_type or namespace_of(module) is not namespace
                    or length(namespace) > max_keys
                    or some(kind(key) is not plain_str for key in namespace)):
                raise error_type(prefix)
        for module, name, original in edges:
            if namespace_of(module).get(name, missing) is not original:
                raise error_type(prefix)
        if factory.__wrapped__ is not wrapped:
            raise error_type(prefix)
        for name, original in builtin_bindings:
            if builtin_namespace.get(name, missing) is not original:
                raise error_type(prefix)
        for namespace, original, domain in builtin_domains:
            if (namespace.get("__builtins__", missing) is not original
                    or length(domain) > max_keys
                    or some(kind(key) is not plain_str for key in domain)):
                raise error_type(prefix)
            for name, value in builtin_bindings:
                if namespace.get(name, value) is not value or domain.get(name, missing) is not value:
                    raise error_type(prefix)
        current = namespace_of(quoter)
        if (quoter.__bases__ is not quoter_bases or quoter.__mro__ is not quoter_mro
                or length(current) != length(quoter_members)
                or some(kind(key) is not plain_str for key in current)):
            raise error_type(prefix)
        for name, original in quoter_members:
            if current.get(name, missing) is not original:
                raise error_type(prefix)
        for name, original in sqlite_descriptors:
            declaration = (cursor_type if name.startswith("cursor.") else connection_type)
            field = name.removeprefix("cursor.")
            if namespace_of(declaration).get(field, missing) is not original:
                raise error_type(prefix)
        for pin in pins:
            (module, name, function, code, namespace, defaults, kwdefaults, kwitems,
             closure, captures, attributes, attritems, annotations, annotationitems,
             label, qualname, module_name, doc) = pin
            if (kind(function) is not function_type or function.__code__ is not code
                    or function.__globals__ is not namespace or function.__defaults__ is not defaults
                    or function.__kwdefaults__ is not kwdefaults or function.__closure__ is not closure
                    or function.__dict__ is not attributes or function.__annotations__ is not annotations):
                raise error_type(prefix)
            for mapping, entries in ((kwdefaults, kwitems), (attributes, attritems),
                                     (annotations, annotationitems)):
                if mapping is None:
                    continue
                if (kind(mapping) is not plain_dict or length(mapping) != length(entries)
                        or some(kind(key) is not plain_str for key in mapping)
                        or plain_set(mapping) != {key for key, _value in entries}):
                    raise error_type(prefix)
                for field, value in entries:
                    if mapping.get(field, missing) is not value:
                        raise error_type(prefix)
            for cell, value in pairs(closure or (), captures):
                try:
                    if cell.cell_contents is not value:
                        raise error_type(prefix)
                except value_error:
                    raise error_type(prefix) from None
            for value, original in ((function.__name__, label), (function.__qualname__, qualname),
                                    (function.__module__, module_name), (function.__doc__, doc)):
                if kind(value) is not kind(original) or value != original:
                    raise error_type(prefix)
        publication = registry.get(publication_name)
        if kind(publication) is not module_type:
            raise error_type(prefix)
        namespace = namespace_of(publication)
        if length(namespace) > max_keys or some(kind(key) is not plain_str for key in namespace):
            raise error_type(prefix)
        if namespace.get("_ORIGINAL_READY_CONDITION_ASSERT") is not condition_assert:
            raise error_type(prefix)
        owner_class = namespace.get("_BRSLineageCheckpointOwner")
        if kind(owner_class) is not kind:
            # The class is resolved only after its enclosing module is initialized.
            raise error_type(prefix)
        if namespace_of(owner_class).get("retain_rejection_ready_capture") is not method:
            raise error_type(prefix)
        return {"protocol": protocol, "sha256": digest}

    return project


rejection_ready_capture_policy = _build_policy()
