"""Held finite executable graph for the private reserved BRS composition.

The enclosing original-run policy pins this entry point and its source. A lazy
first build avoids publication/controller/completion import cycles; it is made
before the original run's policy is retained. Nothing here observes an owner,
opens a ledger, selects a child or grants execution/publication authority.
"""
from __future__ import annotations

import builtins
import dataclasses
import hashlib
import importlib
import json
import math
import os
import sqlite3
import stat
import sys
import threading
import time
import types
from pathlib import Path

from .rsi_learning import RSILearningError

_MODULE_NAMES = (
    "rsi_brs_reserved_wave", "rsi_brs_lineage_prefix", "rsi_brs_reserved_ledger",
    "rsi_brs_reserved_reservation", "rsi_brs_preparation_exchange", "rsi_brs_reserved_rejection",
    "rsi_brs_reserved_owner", "rsi_brs_rejection_owner", "rsi_brs_rejection_provenance",
    "rsi_brs_rejection_capacity", "rsi_brs_rejection_ready_owner", "rsi_brs_rejection_ready_final",
    "rsi_brs_serial_driver", "rsi_brs_native_provider", "rsi_brs_native_completion",
    "rsi_brs_serial_finalization", "rsi_brs_serial_budget", "rsi_checkpoint_storage",
    "rsi_python_brs_terminal_lifecycle", "rsi_brs_terminal_evidence",
    "static_python_fixed_runtime_observation",
)
_PROJECT = None


def _build_reserved_brs_policy():
    kind, length, namespace_of = type, len, vars
    some, pairs = any, zip
    plain_dict, plain_list, plain_tuple = dict, list, tuple
    plain_str, plain_bytes, plain_int, plain_float, plain_bool = str, bytes, int, float, bool
    plain_set, plain_frozenset = set, frozenset
    function_type, module_type = types.FunctionType, types.ModuleType
    proxy_type = types.MappingProxyType
    static_type, class_type, property_type = staticmethod, classmethod, property
    field_type = type(__import__("dataclasses").field())
    object_id, object_get, type_get = id, object.__getattribute__, type.__getattribute__
    error_type, value_error = RSILearningError, ValueError
    registry, own_namespace, sys_namespace = sys.modules, globals(), vars(sys)
    builtin_namespace = vars(builtins)
    fail_message = "rsi_brs_reserved_policy_drift"
    maximum = 32768
    missing = object()
    modules = plain_tuple(importlib.import_module("." + name, __package__) for name in _MODULE_NAMES)
    functions, declarations, queued, declared = [], [], plain_set(), plain_set()

    def fail():
        raise error_type(fail_message)

    def freeze(value, depth=0, remaining=None):
        if remaining is None:
            remaining = [100_000]
        remaining[0] -= 1
        if depth > 48 or remaining[0] < 0:
            fail()
        scalar = kind(value)
        if value is None:
            return "none",
        if scalar is plain_str:
            return "str", value
        if scalar is plain_bytes:
            return "bytes", value
        if scalar is plain_int:
            return "int", value
        if scalar is plain_bool:
            return "bool", value
        if scalar is plain_float:
            if not math.isfinite(value):
                fail()
            return "float", value
        if (scalar is plain_dict or scalar is proxy_type or scalar is plain_list
                or scalar is plain_tuple or scalar is plain_set or scalar is plain_frozenset):
            if length(value) > maximum:
                fail()
            if scalar is plain_dict or scalar is proxy_type:
                return "mapping", object_id(scalar), object_id(value), plain_frozenset(
                    (freeze(key, depth + 1, remaining), freeze(item, depth + 1, remaining))
                    for key, item in value.items())
            items = plain_tuple(freeze(item, depth + 1, remaining) for item in value)
            if scalar is plain_set or scalar is plain_frozenset:
                # No arbitrary ordering/comparison of values or foreign hooks.
                return "set", object_id(scalar), object_id(value), plain_frozenset(items)
            return "sequence", object_id(scalar), object_id(value), items
        if scalar is field_type:
            return "field", object_id(value), plain_tuple(
                (name, freeze(object_get(value, name), depth + 1, remaining)) for name in (
                    "name", "type", "default", "default_factory", "init", "repr", "hash", "compare",
                    "metadata", "kw_only", "_field_type"))
        return "opaque", object_id(scalar), object_id(value)

    def matches_frozen(value, held, depth=0, remaining=None):
        # The baseline is the original immutable freeze shape, not a result
        # cache. Every call still reads the live value at its original scan.
        scalar = kind(value)
        if scalar is proxy_type or scalar is plain_set or scalar is plain_frozenset:
            return freeze(value, depth, remaining) == held
        if scalar is plain_dict:
            if length(value) > maximum:
                fail()
            if (held[0] != "mapping" or held[1] != object_id(scalar)
                    or held[2] != object_id(value)):
                return False
            entries = held[3]
            if length(value) != length(entries):
                return False
            # Only exact str keys permit hook-free direct dictionary lookups.
            # Heterogeneous keys retain the original unordered freeze path.
            if some(key[0] != "str" for key, _item in entries):
                return freeze(value, depth, remaining) == held
        if remaining is None:
            remaining = [100_000]
        remaining[0] -= 1
        if depth > 48 or remaining[0] < 0:
            fail()
        if value is None:
            return held == ("none",)
        if scalar is plain_str:
            return held[0] == "str" and value == held[1]
        if scalar is plain_bytes:
            return held[0] == "bytes" and value == held[1]
        if scalar is plain_int:
            return held[0] == "int" and value == held[1]
        if scalar is plain_bool:
            return held[0] == "bool" and value == held[1]
        if scalar is plain_float:
            if not math.isfinite(value):
                fail()
            return held[0] == "float" and value == held[1]
        if scalar is plain_dict:
            if not entries:
                return length(value) == 0
            # This temporary index contains only held exact str keys. It is
            # rebuilt on every observation and stores no validation result.
            # Never key-lookup in the live dict: a concurrent foreign insertion
            # could otherwise make a lookup execute the inserted key's __eq__.
            expected_items = plain_dict((key[1], expected) for key, expected in entries)
            seen = 0
            for key, item in value.items():
                if kind(key) is not plain_str:
                    return False
                remaining[0] -= 1
                if depth + 1 > 48 or remaining[0] < 0:
                    fail()
                expected = expected_items.get(key, missing)
                if expected is missing:
                    return False
                if not matches_frozen(item, expected, depth + 1, remaining):
                    return False
                seen += 1
            return seen == length(entries)
        if scalar is plain_list or scalar is plain_tuple:
            if length(value) > maximum:
                fail()
            if (held[0] != "sequence" or held[1] != object_id(scalar)
                    or held[2] != object_id(value) or length(value) != length(held[3])):
                return False
            for item, expected in pairs(value, held[3], strict=True):
                if not matches_frozen(item, expected, depth + 1, remaining):
                    return False
            return True
        if scalar is field_type:
            if held[0] != "field" or held[1] != object_id(value):
                return False
            # freeze's immutable tuple supplies exactly its original fixed names.
            for name, expected in held[2]:
                if not matches_frozen(object_get(value, name), expected, depth + 1, remaining):
                    return False
            return True
        return (held[0] == "opaque" and held[1] == object_id(scalar)
                and held[2] == object_id(value))

    def pack_function(function):
        if kind(function) is not function_type or object_id(function) in queued:
            return
        queued.add(object_id(function))
        # A contextmanager wrapper keeps the original generator in both its
        # closure and __wrapped__. Pin its executable body, not just that alias.
        pack_function(getattr(function, "__wrapped__", None))
        mappings = (function.__dict__, function.__annotations__, function.__kwdefaults__)
        if some(mapping is not None and kind(mapping) is not plain_dict for mapping in mappings):
            fail()
        names = function.__code__.co_names
        if (function.__module__ == __package__ + ".rsi_native_scheduler" and function.__qualname__ in (
                "NativeRSISchedulerProvider.__call__", "NativeRSISchedulerProvider.recover_live_rejection")):
            # Their private branch imports the separately held BRS module. The
            # unused legacy branches retain their existing public seam policy.
            names = ()
        names = plain_tuple(name for name in names if not (
            function.__module__ == __package__ + ".rsi_producer_launch" and name == "MAX_STAGING_BINDING_BYTES"
            or function.__module__ == __package__ + ".rsi_producer_staging_capsule" and name == "MAX_READY_BINDING_BYTES"))
        functions.append((function, function.__code__, function.__globals__, function.__defaults__,
            function.__kwdefaults__, function.__closure__,
            plain_tuple(cell.cell_contents for cell in (function.__closure__ or ())),
            freeze(function.__defaults__), freeze(function.__kwdefaults__), freeze(function.__dict__),
            freeze(function.__annotations__), function.__name__, function.__qualname__, function.__module__,
            function.__doc__, plain_tuple((name, function.__globals__.get(name, missing),
                freeze(function.__globals__[name]) if function.__module__.startswith(__package__ + ".")
                    and name in function.__globals__ and
                    some(kind(function.__globals__[name]) is expected for expected in
                        (plain_dict, plain_list, plain_tuple, plain_set, plain_frozenset)) else None)
                for name in names)))

    def pack_class(declaration):
        if kind(declaration) is not type or object_id(declaration) in declared:
            return
        declared.add(object_id(declaration))
        members = type_get(declaration, "__dict__")
        declarations.append((declaration, type_get(declaration, "__mro__"), plain_tuple(members.items()),
            plain_tuple((name, freeze(value)) for name, value in members.items()
                if some(kind(value) is expected for expected in
                    (plain_dict, proxy_type, plain_list, plain_tuple, plain_set, plain_frozenset)))))
        for member in members.values():
            if kind(member) is function_type:
                pack_function(member)
            elif kind(member) is static_type or kind(member) is class_type:
                pack_function(member.__func__)
            elif kind(member) is property_type:
                for function in (member.fget, member.fset, member.fdel):
                    pack_function(function)

    namespaces = []
    for module in modules:
        namespace = namespace_of(module)
        if length(namespace) > maximum or some(kind(key) is not plain_str for key in namespace):
            fail()
        namespaces.append((module, namespace, plain_tuple((name, value) for name, value in namespace.items()
                                                           if name != "__warningregistry__"),
            plain_tuple((name, freeze(value)) for name, value in namespace.items()
                if name != "__warningregistry__" and some(kind(value) is expected for expected in
                    (plain_dict, plain_list, plain_tuple, plain_set, plain_frozenset)))))
        for value in namespace.values():
            if kind(value) is function_type:
                pack_function(value)
            elif kind(value) is type:
                members = type_get(value, "__dict__")
                if (members.get("__module__") == namespace.get("__name__")
                        or kind(members.get("__dataclass_fields__")) is plain_dict):
                    pack_class(value)
    # Explicit preclaim/staging/read-only edges outside the new modules.
    external = (
        ("rsi_controller", "RSILearningController", (
            "_python_admission_assert_reserved_brs_child", "_drive_reserved_brs_native_serial",
            "_python_admission_active_brs_owner", "_python_admission_bind_selected_brs_handoff",
            "_python_admission_brs_full_gate_scope",
            "_stage_producer_episode", "_commit_flow", "_resume_reserved_brs_native_serial",
            "_memory_item", "_decision_from_dict", "_deserialize_execution", "_flow_result",
            "_serialize_execution")),
        ("rsi_producer_gateway", "PythonProducerRSISolverGateway", (
            "run", "bind_reserved_brs_child_controller")),
        ("rsi_producer_launch", "PythonProducerEpisodeStager", (
            "stage", "validate_state", "assert_unattempted", "pure_preflight")),
        ("rsi_python_brs_admission", "BRSAdmissionChannel", (
            "service", "assert_selected_handoff_acknowledged")),
        ("rsi_native_scheduler", "NativeRSISchedulerProvider", (
            "__call__", "recover_live_rejection", "assert_rejection_ledger", "_inputs",
            "rsi_fingerprint_config", "_failure_claim", "validate_preclaim", "_native_rejection_snapshot",
            "provenance_batch", "_python_publication_join")),
        ("rsi_native_scheduler", "NativeRSISchedulerContext", (
            "__post_init__", "_assert_live_modules_sink", "_live_modules_sink_projection",
            "_python_handoff_suppliers")),
        ("native_fixed_live_sink", "FixedPythonLiveSinkRequest", ("validate", "compare")),
        ("native_fixed_live_sink", "_FixedPythonLiveSinkPin", ("__init__", "assert_current", "to_dict")),
        ("static_python_fixed_profile", "FixedPythonInstallation", ("to_dict",)),
        ("rsi_store", "RSILedger", ("_select_python_producer_checkpoint_tx",
            "_validate_python_producer_staging_history_tx", "resolve_python_producer_checkpoint",
            "_python_admission_state_tx", "_controller_checkpoint_history_tx",
            "_controller_checkpoint_history_rows_tx", "_checkpoint_projection_cache", "_checkpoint_projection_scope",
            "_controller_checkpoint_history_observation_tx", "append_brs_terminal_observation",
            "_append_controller_checkpoint_tx", "_append_transfer_checkpoint_tx", "_checkpoint_digest",
            "_create", "transition")),
        ("rsi_store", "_CheckpointHistoryRowProjection", ("__init__",)),
    )
    external_members = []
    for module_name, class_name, names in external:
        module = importlib.import_module("." + module_name, __package__)
        declaration = namespace_of(module)[class_name]
        for name in names:
            function = type_get(declaration, "__dict__")[name]
            if kind(function) is property_type:
                for accessor in (function.fget, function.fset, function.fdel):
                    pack_function(accessor)
            elif kind(function) is static_type or kind(function) is class_type:
                pack_function(function.__func__)
            else:
                pack_function(function)
            external_members.append((declaration, name, function))
    for module_name, names in (
        ("rsi_controller", ("_record_digest",)),
        ("rsi_store", ("_admission_checkpoint_helpers_current", "_admission_checkpoint_projection",
            "_checkpoint_projection_helpers_current", "_checkpoint_projection_constant", "_checkpoint_projection_key",
            "_retain_checkpoint_projection", "_build_checkpoint_projection_pins")),
        ("native_fixed_live_sink", ("_pin_fixed_python_live_sink_request",)),
        ("static_python_fixed_profile", ("_reparse", "_parse_installation", "verify_fixed_python_image")),
        ("static_python_fixed_live_modules", (
            "_compose", "compare_fixed_python_bound_live_modules", "_compare_live_payload")),
        ("native_trusted_scheduler", ("_run_native_trusted_producer",
            "_prepare_native_trusted_python_producer", "run_native_trusted_producer",
            "run_native_trusted_producer_outcome", "_prepublication_evidence", "_native_handoff_evidence")),
        ("rsi_python_episode_inputs", ("_resolve_python_rsi_episode_input_context",
            "resolve_reserved_python_rsi_episode_input_context", "resolve_python_rsi_episode_input_context")),
        ("rsi_producer_gateway", ("resolve_reserved_python_producer_episode_gateway",)),
    ):
        module = importlib.import_module("." + module_name, __package__)
        for name in names:
            function = namespace_of(module)[name]
            pack_function(function)
            external_members.append((module, name, function))
    builtin_names = ("type", "len", "vars", "any", "all", "zip", "sorted", "dict", "list", "tuple", "set",
        "frozenset", "str", "bytes", "int", "float", "bool", "getattr", "hasattr", "isinstance", "range",
        "enumerate", "sum", "max", "min", "object", "id", "Exception", "BaseException", "ValueError",
        "TypeError", "KeyError", "AttributeError", "OSError", "FileNotFoundError", "OverflowError",
        "RecursionError", "UnicodeError", "__import__")
    builtin_bindings = plain_tuple((name, builtin_namespace[name]) for name in builtin_names)
    runtime_edges = plain_tuple((module, namespace_of(module), name, namespace_of(module)[name])
        for module, names in (
            (dataclasses, ("fields",)),
            (hashlib, ("sha256",)), (json, ("loads", "dumps")),
            (math, ("isfinite",)), (time, ("time", "monotonic")),
            (os, ("fstat", "lstat", "listdir", "stat", "open", "read", "close")),
            (stat, ("S_ISREG", "S_IMODE")),
            (threading, ("get_ident", "current_thread", "Condition", "RLock")),
            (sqlite3, ("connect", "Row", "Connection")),
        ) for name in names)
    for module, _namespace, _name, value in runtime_edges:
        if kind(value) is function_type:
            pack_function(value)
    builtin_domains = []
    builtin_namespaces = plain_set()
    unique_builtin_domains = []
    builtin_domain_ids = plain_set()
    for function, _code, namespace, *_tail in functions:
        # Functions sharing globals have the same builtin alias and shadow
        # vector. Observe every distinct namespace on each projection without
        # repeating this identical scan once per function. The function pins
        # below still retain every function and its original globals object.
        namespace_identity = object_id(namespace)
        if namespace_identity in builtin_namespaces:
            continue
        builtin_namespaces.add(namespace_identity)
        value = namespace.get("__builtins__")
        domain = namespace_of(value) if kind(value) is module_type else value
        if kind(domain) is not plain_dict:
            fail()
        domain_identity = object_id(domain)
        if domain_identity not in builtin_domain_ids:
            builtin_domain_ids.add(domain_identity)
            unique_builtin_domains.append(domain)
        builtin_domains.append((namespace, value, domain,
            plain_tuple((name, namespace.get(name, original)) for name, original in builtin_bindings)))
    registered_modules = plain_dict((module.__name__, module) for module in modules)
    for declaration, _name, _original in external_members:
        module = declaration if kind(declaration) is module_type else registry[declaration.__module__]
        registered_modules[module.__name__] = module
    for module, _namespace, _name, _value in runtime_edges:
        registered_modules[module.__name__] = module
    declared_limits = plain_tuple((module, namespace_of(module), module.__name__, name)
        for module_name, name in (("rsi_producer_launch", "MAX_STAGING_BINDING_BYTES"),
                                 ("rsi_producer_staging_capsule", "MAX_READY_BINDING_BYTES"))
        for module in (importlib.import_module("." + module_name, __package__),))
    for module, _namespace, label, _name in declared_limits:
        registered_modules[label] = module
    registered = plain_tuple(registered_modules.items())
    source_modules = plain_dict((module.__name__, module) for module in modules)
    for declaration, _name, _original in external_members:
        module = declaration if kind(declaration) is module_type else registry[declaration.__module__]
        source_modules[module.__name__] = module
    for module, _namespace, label, _name in declared_limits:
        source_modules[label] = module
    sources = {name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
               for name, module in source_modules.items()}
    projection = {"protocol": "lunar-rsi-brs-reserved-executable-policy-v1", "sources": sources,
                  "scope": "private-original-reservation-composition; no-authority"}
    digest = hashlib.sha256(json.dumps(projection, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    protocol = projection["protocol"]
    functions, declarations, namespaces = plain_tuple(functions), plain_tuple(declarations), plain_tuple(namespaces)
    unique_builtin_domains = plain_tuple(unique_builtin_domains)
    external_members = plain_tuple(external_members)
    # ``warnings`` may lazily add a module-level ``__warningregistry__`` after
    # this policy is first projected (for example when a worker emits a
    # ResourceWarning).  It is interpreter bookkeeping, not executable policy
    # input; pin every other module-global exactly as before.
    own_aliases = plain_tuple((name, value) for name, value in own_namespace.items()
        if name not in ("_PROJECT", "__warningregistry__"))
    own_names = plain_frozenset(name for name, _value in own_aliases)
    # Check these helpers before invoking either: a function object can retain
    # its identity while its executable code or a closure cell is replaced.
    helper_pins = plain_tuple((function, function.__code__, function.__globals__,
        function.__defaults__, function.__kwdefaults__, function.__closure__,
        plain_tuple(cell.cell_contents for cell in (function.__closure__ or ())))
        for function in (fail, freeze, matches_frozen))

    def project():
        for expected, pin in pairs((fail, freeze, matches_frozen), helper_pins, strict=True):
            function, code, namespace, defaults, kwdefaults, closure, captures = pin
            if (function is not expected or kind(function) is not function_type or function.__code__ is not code
                    or function.__globals__ is not namespace or function.__defaults__ is not defaults
                    or function.__kwdefaults__ is not kwdefaults or function.__closure__ is not closure):
                raise error_type(fail_message)
            for cell, value in pairs(closure or (), captures, strict=True):
                try:
                    if cell.cell_contents is not value:
                        raise error_type(fail_message)
                except value_error:
                    raise error_type(fail_message) from None
        warning_registry = own_namespace.get("__warningregistry__", missing)
        if (some(kind(key) is not plain_str for key in own_namespace)
                or any(name not in own_names for name in own_namespace
                       if name not in ("_PROJECT", "__warningregistry__"))
                or own_namespace.get("_PROJECT", missing) is not project
                or (warning_registry is not missing and kind(warning_registry) is not plain_dict)):
            fail()
        if (namespace_of(sys) is not sys_namespace or sys_namespace.get("modules", missing) is not registry
                or length(registry) > maximum or some(kind(key) is not plain_str for key in registry)):
            fail()
        for name, value in own_aliases:
            if own_namespace.get(name, missing) is not value:
                fail()
        for name, module in registered:
            if registry.get(name, missing) is not module:
                fail()
        for name, original in builtin_bindings:
            if builtin_namespace.get(name, missing) is not original:
                fail()
        for module, namespace, name, original in runtime_edges:
            if namespace_of(module) is not namespace or namespace.get(name, missing) is not original:
                fail()
        for module, namespace, saved, containers in namespaces:
            if (kind(module) is not module_type or namespace_of(module) is not namespace
                    or some(kind(key) is not plain_str for key in namespace)):
                fail()
            warning_registry = namespace.get("__warningregistry__", missing)
            if warning_registry is not missing and kind(warning_registry) is not plain_dict:
                fail()
            names = plain_frozenset(name for name in namespace if name != "__warningregistry__")
            if len(names) != len(saved) or names != plain_frozenset(name for name, _value in saved):
                fail()
            for name, value in saved:
                if namespace.get(name, missing) is not value:
                    fail()
            for name, value in containers:
                if not matches_frozen(namespace[name], value):
                    fail()
        for declaration, name, original in external_members:
            namespace = namespace_of(declaration) if kind(declaration) is module_type else type_get(declaration, "__dict__")
            if namespace.get(name, missing) is not original:
                fail()
        for declaration, hierarchy, saved, containers in declarations:
            members = type_get(declaration, "__dict__")
            if (type_get(declaration, "__mro__") is not hierarchy or length(members) != length(saved)
                    or some(kind(name) is not plain_str for name in members)):
                fail()
            for name, value in saved:
                if members.get(name, missing) is not value:
                    fail()
            for name, value in containers:
                if not matches_frozen(members[name], value):
                    fail()
        # Check each held domain once, while retaining the alias and complete
        # shadow vector separately for every globals namespace below. These
        # sequential live observations do not provide an atomic snapshot.
        for domain in unique_builtin_domains:
            if length(domain) > maximum or some(kind(key) is not plain_str for key in domain):
                fail()
            for name, value in builtin_bindings:
                if domain.get(name, missing) is not value:
                    fail()
        for namespace, original, _domain, shadows in builtin_domains:
            if namespace.get("__builtins__", missing) is not original:
                fail()
            for (name, value), (_label, builtin) in pairs(shadows, builtin_bindings, strict=True):
                if namespace.get(name, builtin) is not value:
                    fail()
        for pin in functions:
            (function, code, namespace, defaults, kwdefaults, closure, captures,
             default_value, kw_value, attrs, annotations, label, qualified, module_name, doc, globals_used) = pin
            if (kind(function) is not function_type or function.__code__ is not code
                    or function.__globals__ is not namespace or function.__defaults__ is not defaults
                    or function.__kwdefaults__ is not kwdefaults or function.__closure__ is not closure):
                fail()
            if (not matches_frozen(function.__defaults__, default_value)
                    or not matches_frozen(function.__kwdefaults__, kw_value)
                    or not matches_frozen(function.__dict__, attrs)
                    or not matches_frozen(function.__annotations__, annotations)):
                fail()
            for name, value, container in globals_used:
                if namespace.get(name, missing) is not value:
                    fail()
                if container is not None and not matches_frozen(namespace[name], container):
                    fail()
            for cell, value in pairs(closure or (), captures, strict=True):
                try:
                    if cell.cell_contents is not value:
                        fail()
                except value_error:
                    fail()
            for value, original in ((function.__name__, label), (function.__qualname__, qualified),
                                    (function.__module__, module_name), (function.__doc__, doc)):
                if kind(value) is not kind(original) or value != original:
                    fail()
        # Existing local fixtures vary these staging limits. Include their live
        # exact values in each identity, so an original run still refuses drift,
        # without making a prior unrelated run's limits a process-wide baseline.
        limits = []
        for module, namespace, label, name in declared_limits:
            value = namespace.get(name, missing)
            if (namespace_of(module) is not namespace or kind(value) is not plain_int
                    or not 0 < value < 2**63):
                fail()
            limits.append([label, name, value])
        actual = hashlib.sha256(json.dumps({"graph": digest, "limits": limits},
            sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return {"protocol": protocol, "sha256": actual}

    return project


def _build_reserved_brs_policy_entry():
    # The enclosing policy independently pins this entry's original closure
    # cells. The one-time latch never substitutes a caller-provided projection.
    kind, pairs, length, plain_tuple = type, zip, len, tuple
    function_type, tuple_type, list_type = types.FunctionType, tuple, list
    error_type, value_error = RSILearningError, ValueError
    namespace, builder, cache = globals(), _build_reserved_brs_policy, []
    message = "rsi_brs_reserved_policy_drift"

    def entry():
        if kind(cache) is not list_type or length(cache) > 1:
            raise error_type(message)
        if not cache:
            if namespace.get("_PROJECT") is not None:
                raise error_type(message)
            project = builder()
            if kind(project) is not function_type:
                raise error_type(message)
            cache.append((project, project.__code__, project.__globals__, project.__defaults__,
                project.__kwdefaults__, project.__closure__,
                plain_tuple(cell.cell_contents for cell in (project.__closure__ or ()))))
            namespace["_PROJECT"] = project
        pin = cache[0]
        if kind(pin) is not tuple_type or length(pin) != 7:
            raise error_type(message)
        project, code, original_globals, defaults, kwdefaults, closure, captures = pin
        if (kind(project) is not function_type or namespace.get("_PROJECT") is not project
                or project.__code__ is not code or project.__globals__ is not original_globals
                or project.__defaults__ is not defaults or project.__kwdefaults__ is not kwdefaults
                or project.__closure__ is not closure or kind(captures) is not tuple_type):
            raise error_type(message)
        for cell, value in pairs(closure or (), captures, strict=True):
            try:
                if cell.cell_contents is not value:
                    raise error_type(message)
            except value_error:
                raise error_type(message) from None
        return project()

    return entry


reserved_brs_policy_projection = _build_reserved_brs_policy_entry()
