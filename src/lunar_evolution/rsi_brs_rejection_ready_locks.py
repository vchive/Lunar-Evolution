"""Original native lock custody, without acquiring locks or granting authority.

The tuple is comparison data for the private staged-ready implementation.  It
does not prove a controller lease, transfer ownership, or authorize an ACK.  The
caller independently pins these entry points before capturing any owner state.
"""

from __future__ import annotations

import _thread
import builtins
import sys
import threading
import types

from . import automatic_solve_lifecycle as control_module
from . import rsi_controller as controller_module
from . import rsi_learning as learning_module
from . import rsi_store as ledger_module


def _build_guards():
    kind, length, namespace_of, some, pairs = type, len, vars, any, zip
    plain_dict, plain_str, plain_tuple, plain_set = dict, str, tuple, set
    object_type, function_type, module_type = object, types.FunctionType, types.ModuleType
    value_error = ValueError
    error_type = learning_module.RSILearningError
    error_new = BaseException.__new__
    error_dict = namespace_of(BaseException)["__dict__"]
    dict_set = dict.__setitem__
    lock_type = _thread.RLock
    thread_id = _thread.get_ident
    controller_type = controller_module.RSILearningController
    ledger_type = ledger_module.RSILedger
    control_type = control_module.SolveExecutionControl
    registry, own_namespace = sys.modules, globals()
    max_keys = 16384
    prefix = "rsi_brs_rejection_ready_locks_"
    missing = object_type()
    class_readers = (
        (controller_type, ("_python_admission_brs_observations",)),
        (ledger_type, ("controller_lock_held", "_assert_controller_lock",
                       "read_only_observations", "_connect")),
        (control_type, ("is_cancelled", "check", "remaining", "effective_timeout", "_now")),
    )
    class_pins = plain_tuple((declared, declared.__bases__, declared.__mro__,
                              plain_tuple(namespace_of(declared).items()))
                             for declared, _readers in class_readers)
    dict_descriptor_get = types.GetSetDescriptorType.__get__
    dict_descriptors = plain_tuple(namespace_of(declared)["__dict__"]
                                   for declared, _readers in class_readers)
    native_descriptors = plain_tuple((name, namespace_of(lock_type)[name]) for name in (
        "acquire", "release", "_is_owned", "_release_save", "_acquire_restore",
        "__enter__", "__exit__"))

    def pack(function):
        return (function, function.__code__, function.__globals__, function.__defaults__,
                function.__kwdefaults__, plain_tuple((function.__kwdefaults__ or {}).items()),
                function.__closure__, plain_tuple(cell.cell_contents
                                                  for cell in (function.__closure__ or ())),
                function.__dict__, plain_tuple(function.__dict__.items()),
                function.__annotations__, plain_tuple(function.__annotations__.items()),
                function.__name__, function.__qualname__, function.__module__, function.__doc__)

    def make_error(message):
        # Refusals must not re-enter a changed Python error initializer or its
        # builtin super(). These are held C allocation/descriptor/dict operations.
        error = error_new(error_type, message)
        dictionary = dict_descriptor_get(error_dict, error, error_type)
        dict_set(dictionary, "code", message)
        return error

    def shape(controller, ledger, control):
        objects = (controller, ledger, control)
        namespaces = []
        locks = []
        names = ("_python_admission_brs_observation_lock", "_controller_guards_lock", "_lock")
        for index, ((declared, readers), descriptor, name, value) in enumerate(
                pairs(class_readers, dict_descriptors, names, objects)):
            if index == 2 and value is None:
                namespaces.append(None)
                locks.append(None)
                continue
            if kind(value) is not declared:
                raise make_error(prefix + "instance_type")
            namespace = dict_descriptor_get(descriptor, value, declared)
            if (kind(namespace) is not plain_dict or length(namespace) > max_keys
                    or some(kind(key) is not plain_str for key in namespace)):
                raise make_error(prefix + "instance_shape")
            # Only the explicit reader surface is forbidden.  Inert fixtures
            # retain their unrelated _execute_intent boundary unchanged.
            if some(reader in namespace for reader in readers):
                raise make_error(prefix + "reader_shadow")
            lock = namespace.get(name, missing)
            if kind(lock) is not lock_type:
                raise make_error(prefix + "native_lock_type")
            namespaces.append(namespace)
            locks.append(lock)
        current_thread = thread_id()
        if kind(current_thread) is not int:
            raise make_error(prefix + "thread_type")
        return (*objects, *locks, *namespaces, current_thread)

    function_pins = [pack(shape), pack(make_error), pack(error_type.__init__)]
    for declared, readers in class_readers:
        for name in readers:
            function = namespace_of(declared)[name]
            function_pins.append(pack(function))
            wrapped = function.__dict__.get("__wrapped__", missing)
            if wrapped is not missing:
                if kind(wrapped) is not function_type:
                    raise make_error(prefix + "function_type")
                function_pins.append(pack(wrapped))
    function_pins = plain_tuple(function_pins)
    modules = plain_tuple((module, namespace_of(module)) for module in (
        _thread, builtins, sys, threading, types, controller_module,
        ledger_module, control_module, learning_module))
    registered = plain_tuple((module.__name__, module) for module, _namespace in modules)
    builtin_namespace = namespace_of(builtins)
    builtin_names = ("type", "len", "vars", "any", "zip", "dict", "str", "tuple", "set",
                     "object", "int", "enumerate", "ValueError", "BaseException", "super")
    builtin_bindings = plain_tuple((name, builtin_namespace[name]) for name in builtin_names)
    edges = (
        (_thread, "RLock", lock_type), (_thread, "get_ident", thread_id),
        (threading, "get_ident", thread_id), (threading, "_CRLock", lock_type),
        (threading, "RLock", threading.RLock),
        (controller_module, "RLock", threading.RLock),
        (controller_module, "get_ident", thread_id),
        (ledger_module, "threading", threading), (control_module, "RLock", threading.RLock),
        (controller_module, "RSILearningController", controller_type),
        (ledger_module, "RSILedger", ledger_type),
        (control_module, "SolveExecutionControl", control_type),
        (learning_module, "RSILearningError", error_type),
        (types, "FunctionType", function_type), (types, "ModuleType", module_type),
        (types, "GetSetDescriptorType", types.GetSetDescriptorType),
    )
    lookup_pins = plain_tuple((name, namespace_of(object_type)[name])
                              for name in ("__getattribute__", "__setattr__", "__delattr__"))
    builtin_domains = plain_tuple((pin[2], pin[2].get("__builtins__")) for pin in function_pins)
    own_aliases = ()

    def runtime():
        if (length(own_namespace) > max_keys
                or some(kind(key) is not plain_str for key in own_namespace)
                or some(own_namespace.get(name, missing) is not original
                        for name, original in own_aliases)):
            raise make_error(prefix + "guard_alias")
        for module, namespace in modules:
            if (kind(module) is not module_type or namespace_of(module) is not namespace
                    or length(namespace) > max_keys
                    or some(kind(key) is not plain_str for key in namespace)):
                raise make_error(prefix + "module_drift")
        if (sys.modules is not registry or kind(registry) is not plain_dict
                or length(registry) > max_keys or some(kind(key) is not plain_str for key in registry)):
            raise make_error(prefix + "module_registry")
        for name, module in registered:
            if registry.get(name, missing) is not module:
                raise make_error(prefix + "module_registry")
        for module, name, original in edges:
            if namespace_of(module).get(name, missing) is not original:
                raise make_error(prefix + "alias_drift")
        for name, original in builtin_bindings:
            if builtin_namespace.get(name, missing) is not original:
                raise make_error(prefix + "builtin_drift")
        for namespace, original_domain in builtin_domains:
            if namespace.get("__builtins__", missing) is not original_domain:
                raise make_error(prefix + "builtin_drift")
            domain = original_domain
            if kind(domain) is module_type:
                domain = namespace_of(domain)
            if (kind(domain) is not plain_dict or length(domain) > max_keys
                    or some(kind(key) is not plain_str for key in domain)):
                raise make_error(prefix + "builtin_drift")
            for name, original in builtin_bindings:
                if (namespace.get(name, original) is not original
                        or domain.get(name, missing) is not original):
                    raise make_error(prefix + "builtin_drift")
        for declared, bases, mro, members in class_pins:
            current = namespace_of(declared)
            if (declared.__bases__ is not bases or declared.__mro__ is not mro
                    or length(current) != length(members)
                    or some(kind(key) is not plain_str for key in current)
                    or plain_set(current) != {name for name, _value in members}
                    or some(current.get(name, missing) is not original for name, original in members)):
                raise make_error(prefix + "class_drift")
        for name, original in native_descriptors:
            if namespace_of(lock_type).get(name, missing) is not original:
                raise make_error(prefix + "native_descriptor")
        for name, original in lookup_pins:
            if namespace_of(object_type).get(name, missing) is not original:
                raise make_error(prefix + "class_lookup")
        if namespace_of(types.GetSetDescriptorType).get("__get__") is not dict_descriptor_get:
            raise make_error(prefix + "class_lookup")
        for pin in function_pins:
            (function, code, namespace, defaults, kwdefaults, kwitems, closure, captures,
             attributes, attritems, annotations, annotationitems, name, qualname, module, doc) = pin
            if (kind(function) is not function_type or function.__code__ is not code
                    or function.__globals__ is not namespace or function.__defaults__ is not defaults
                    or function.__kwdefaults__ is not kwdefaults or function.__closure__ is not closure
                    or function.__dict__ is not attributes or function.__annotations__ is not annotations):
                raise make_error(prefix + "function_drift")
            for mapping, entries in ((kwdefaults, kwitems), (attributes, attritems),
                                     (annotations, annotationitems)):
                if mapping is None:
                    continue
                if (kind(mapping) is not plain_dict or length(mapping) != length(entries)
                        or some(kind(key) is not plain_str for key in mapping)
                        or plain_set(mapping) != {key for key, _value in entries}
                        or some(mapping.get(key) is not value for key, value in entries)):
                    raise make_error(prefix + "function_drift")
            for cell, value in pairs(closure or (), captures):
                try:
                    if cell.cell_contents is not value:
                        raise make_error(prefix + "function_drift")
                except value_error:
                    raise make_error(prefix + "function_drift") from None
            for value, original in ((function.__name__, name), (function.__qualname__, qualname),
                                    (function.__module__, module), (function.__doc__, doc)):
                if kind(value) is not kind(original) or value != original:
                    raise make_error(prefix + "function_drift")

    runtime_pin = None

    def capture(controller, ledger, control):
        # Independently bootstrap both Python helpers before either can run.
        valid = True
        for expected, pin in ((make_error, error_pin), (runtime, runtime_pin)):
            (function, code, namespace, defaults, kwdefaults, _kwitems, closure, captures,
             attributes, attritems, annotations, annotationitems, name, qualname, module, doc) = pin
            if (function is not expected or kind(function) is not function_type
                    or function.__code__ is not code or function.__globals__ is not namespace
                    or function.__defaults__ is not defaults or function.__kwdefaults__ is not kwdefaults
                    or function.__closure__ is not closure or function.__dict__ is not attributes
                    or function.__annotations__ is not annotations):
                valid = False
            for mapping, entries in ((attributes, attritems), (annotations, annotationitems)):
                if (kind(mapping) is not plain_dict or length(mapping) != length(entries)
                        or some(kind(key) is not plain_str for key in mapping)
                        or plain_set(mapping) != {key for key, _value in entries}
                        or some(mapping.get(key) is not value for key, value in entries)):
                    valid = False
            for cell, value in pairs(closure or (), captures):
                try:
                    if cell.cell_contents is not value:
                        valid = False
                except value_error:
                    valid = False
            for value, original in ((function.__name__, name), (function.__qualname__, qualname),
                                    (function.__module__, module), (function.__doc__, doc)):
                if kind(value) is not kind(original) or value != original:
                    valid = False
        if not valid:
            message = prefix + "checker_drift"
            error = error_new(error_type, message)
            dict_set(dict_descriptor_get(error_dict, error, error_type), "code", message)
            raise error
        runtime()
        return shape(controller, ledger, control)

    def compare(controller, ledger, control, capsule):
        # Keep rejection independent even if the held capture entry point or
        # error-construction helper has been changed in place.
        valid = True
        for expected, pin in ((make_error, error_pin), (capture, capture_pin)):
            (function, code, namespace, defaults, kwdefaults, _kwitems, closure, captures,
             attributes, attritems, annotations, annotationitems, name, qualname, module, doc) = pin
            if (function is not expected or kind(function) is not function_type
                    or function.__code__ is not code or function.__globals__ is not namespace
                    or function.__defaults__ is not defaults or function.__kwdefaults__ is not kwdefaults
                    or function.__closure__ is not closure or function.__dict__ is not attributes
                    or function.__annotations__ is not annotations):
                valid = False
            for mapping, entries in ((attributes, attritems), (annotations, annotationitems)):
                if (kind(mapping) is not plain_dict or length(mapping) != length(entries)
                        or some(kind(key) is not plain_str for key in mapping)
                        or plain_set(mapping) != {key for key, _value in entries}
                        or some(mapping.get(key) is not value for key, value in entries)):
                    valid = False
            for cell, value in pairs(closure or (), captures):
                try:
                    if cell.cell_contents is not value:
                        valid = False
                except value_error:
                    valid = False
            for value, original in ((function.__name__, name), (function.__qualname__, qualname),
                                    (function.__module__, module), (function.__doc__, doc)):
                if kind(value) is not kind(original) or value != original:
                    valid = False
        if not valid:
            message = prefix + "checker_drift"
            error = error_new(error_type, message)
            dict_set(dict_descriptor_get(error_dict, error, error_type), "code", message)
            raise error
        current = capture(controller, ledger, control)
        if kind(capsule) is not plain_tuple or length(capsule) != 10:
            raise make_error(prefix + "capsule_shape")
        if (kind(capsule[9]) is not int or current[9] != capsule[9]
                or some(value is not original for value, original in pairs(current[:9], capsule[:9]))):
            raise make_error(prefix + "custody_drift")

    own_aliases = plain_tuple(own_namespace.items()) + (
        ("capture_rejection_ready_locks", capture), ("assert_rejection_ready_locks", compare))
    capture.__name__ = "capture_rejection_ready_locks"
    compare.__name__ = "assert_rejection_ready_locks"
    error_pin = pack(make_error)
    runtime_pin = pack(runtime)
    capture_pin = pack(capture)
    return capture, compare


capture_rejection_ready_locks, assert_rejection_ready_locks = _build_guards()
