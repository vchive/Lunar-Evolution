"""Pure native lock custody checks, without owners, leases, SQL or ACKs."""

from __future__ import annotations

import _thread
import builtins
import sys
import threading
import types

import pytest

from lunar_evolution import rsi_brs_rejection_ready_locks as locks
from lunar_evolution.automatic_solve_lifecycle import SolveExecutionControl
from lunar_evolution.rsi_controller import RSILearningController
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_store import RSILedger

_CAPTURE = locks.capture_rejection_ready_locks
_ASSERT = locks.assert_rejection_ready_locks
_ERROR = "rsi_brs_rejection_ready_locks_"
_LOCK_NAMES = ("_python_admission_brs_observation_lock", "_controller_guards_lock", "_lock")


def _objects(*, control=True):
    controller = object.__new__(RSILearningController)
    ledger = object.__new__(RSILedger)
    controller._python_admission_brs_observation_lock = threading.RLock()
    ledger._controller_guards_lock = threading.RLock()
    return controller, ledger, SolveExecutionControl(60) if control else None


def _reject(objects, capsule=None):
    with pytest.raises(RSILearningError, match=_ERROR):
        if capsule is None:
            _CAPTURE(*objects)
        else:
            _ASSERT(*objects, capsule)


@pytest.mark.parametrize("control", [False, True])
@pytest.mark.parametrize("held", [False, True])
def test_original_native_locks_are_read_without_acquisition_or_mutation(control, held):
    objects = _objects(control=control)
    capsule = _CAPTURE(*objects)
    before = tuple(dict(vars(value)) if value is not None else None for value in objects)
    assert type(capsule) is tuple and len(capsule) == 10
    assert all(value is original for value, original in zip(capsule[:3], objects))
    assert all(type(value) is _thread.RLock for value in capsule[3:5])
    assert (capsule[5] is None) is not control
    if control:
        assert type(capsule[5]) is _thread.RLock
    for native in capsule[3:6]:
        if held and native is not None:
            native.acquire()
    try:
        _ASSERT(*objects, capsule)
        assert tuple(dict(vars(value)) if value is not None else None for value in objects) == before
        assert all(native._is_owned() is held for native in capsule[3:6] if native is not None)
    finally:
        for native in capsule[3:6]:
            if held and native is not None:
                native.release()


def test_observation_does_not_wait_for_locks_owned_by_another_thread():
    objects = _objects()
    capsule = _CAPTURE(*objects)
    errors, results = [], []
    for native in capsule[3:6]:
        native.acquire()

    def observe():
        try:
            results.append(_CAPTURE(*objects))
        except RSILearningError as error:
            errors.append(error)

    thread = threading.Thread(target=observe)
    thread.start()
    try:
        thread.join(timeout=2)
        assert not thread.is_alive() and not errors and len(results) == 1
        assert results[0][9] != capsule[9]
    finally:
        for native in capsule[3:6]:
            native.release()
        thread.join(timeout=2)


@pytest.mark.parametrize("index", range(3))
def test_equal_kind_lock_replacement_breaks_original_custody(index):
    objects = _objects()
    capsule = _CAPTURE(*objects)
    setattr(objects[index], _LOCK_NAMES[index], threading.RLock())
    _reject(objects, capsule)
    assert capsule[3 + index] is not getattr(objects[index], _LOCK_NAMES[index])


@pytest.mark.parametrize("index", range(3))
@pytest.mark.parametrize("replacement", [None, object(), threading.Lock(), lambda: None])
def test_nonrecursive_or_foreign_lock_is_rejected_before_capture(index, replacement):
    objects = _objects()
    setattr(objects[index], _LOCK_NAMES[index], replacement)
    _reject(objects)


@pytest.mark.parametrize("index", range(3))
def test_native_rlock_subclass_is_not_accepted(index):
    class Foreign(_thread.RLock):
        def acquire(self, *args, **kwargs):
            raise AssertionError("foreign acquire")

    objects = _objects()
    setattr(objects[index], _LOCK_NAMES[index], Foreign())
    _reject(objects)


@pytest.mark.parametrize("index", range(3))
@pytest.mark.parametrize("kind", ["foreign", "subclass"])
def test_noncanonical_instances_are_rejected_before_attribute_callbacks(index, kind):
    objects = list(_objects())
    calls = []
    parent = type(objects[index]) if kind == "subclass" else object

    class Foreign(parent):
        def __getattribute__(self, name):
            calls.append(name)
            raise AssertionError("foreign attribute callback")

    objects[index] = object.__new__(Foreign)
    _reject(objects)
    assert calls == []


@pytest.mark.parametrize("index,names", [
    (0, ("_python_admission_brs_observations",)),
    (1, ("controller_lock_held", "_assert_controller_lock", "read_only_observations", "_connect")),
    (2, ("is_cancelled", "check", "remaining", "effective_timeout", "_now")),
])
def test_relevant_instance_reader_shadows_refuse_without_invocation(index, names):
    objects = _objects()
    capsule = _CAPTURE(*objects)
    calls = []

    def trap(*args, **kwargs):
        calls.append(1)
        raise AssertionError("reader callback")

    for name in names:
        setattr(objects[index], name, trap)
        try:
            _reject(objects)
            _reject(objects, capsule)
        finally:
            delattr(objects[index], name)
    assert calls == []


def test_inert_execution_boundary_is_not_part_of_read_only_lock_surface():
    objects = _objects()
    calls = []

    def trap(*args, **kwargs):
        calls.append(1)
        raise AssertionError("execution boundary")

    objects[0]._execute_intent = trap
    capsule = _CAPTURE(*objects)
    _ASSERT(*objects, capsule)
    assert calls == []


class _EvilKey:
    def __init__(self, name):
        self.name, self.calls = name, 0

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        self.calls += 1
        raise AssertionError("foreign key equality")


@pytest.mark.parametrize("index", range(3))
def test_foreign_instance_mapping_keys_refuse_before_any_lookup(index):
    objects = _objects()
    capsule = _CAPTURE(*objects)
    key = _EvilKey(_LOCK_NAMES[index])
    namespace = vars(objects[index])
    del namespace[_LOCK_NAMES[index]]
    namespace[key] = object()
    _reject(objects)
    _reject(objects, capsule)
    assert key.calls == 0


@pytest.mark.parametrize("capsule", [[], (), (None,) * 9, (None,) * 10, (None,) * 11])
def test_capsule_shape_and_primitive_thread_gate(capsule):
    _reject(_objects(), capsule)


def test_capsule_tuple_subclass_and_foreign_thread_refuse():
    class Foreign(tuple):
        pass

    objects = _objects()
    capsule = _CAPTURE(*objects)
    _reject(objects, Foreign(capsule))
    _reject(objects, (*capsule[:9], True))
    _reject(objects, (*capsule[:9], capsule[9] + 1))
    errors = []

    def observe():
        try:
            _ASSERT(*objects, capsule)
        except RSILearningError as error:
            errors.append(error)

    thread = threading.Thread(target=observe)
    thread.start()
    thread.join(timeout=2)
    assert not thread.is_alive() and len(errors) == 1


@pytest.mark.parametrize("index", range(3))
def test_original_instance_namespace_replacement_is_rejected(index):
    objects = _objects()
    capsule = _CAPTURE(*objects)
    objects[index].__dict__ = dict(vars(objects[index]))
    _reject(objects, capsule)


@pytest.mark.parametrize("index,name", [
    (0, "_python_admission_brs_observations"), (1, "controller_lock_held"),
    (2, "is_cancelled"), (0, "__getattribute__"), (1, "__getattr__"), (2, "__getattribute__"),
])
def test_class_reader_or_lookup_replacement_refuses_before_callbacks(monkeypatch, index, name):
    objects = _objects()
    capsule = _CAPTURE(*objects)
    calls = []

    def trap(*args, **kwargs):
        calls.append(1)
        raise AssertionError("class callback")

    with monkeypatch.context() as patch:
        patch.setattr(type(objects[index]), name, trap, raising=False)
        _reject(objects)
        _reject(objects, capsule)
    assert calls == []


@pytest.mark.parametrize("function", [
    RSILearningController._python_admission_brs_observations,
    RSILearningController._python_admission_brs_observations.__wrapped__,
    RSILedger.controller_lock_held, SolveExecutionControl.is_cancelled,
])
@pytest.mark.parametrize("attribute,replacement", [
    ("__defaults__", (99,)), ("__kwdefaults__", {"foreign": 1}),
    ("__dict__", {"foreign": 1}), ("__annotations__", {"foreign": int}),
    ("__name__", "foreign"), ("__qualname__", "foreign"),
    ("__module__", "foreign"), ("__doc__", "foreign"),
])
def test_function_metadata_is_independently_held(monkeypatch, function, attribute, replacement):
    objects = _objects()
    capsule = _CAPTURE(*objects)
    with monkeypatch.context() as patch:
        patch.setattr(function, attribute, replacement)
        _reject(objects)
        _reject(objects, capsule)


def test_live_reader_function_code_is_rejected_without_invocation(monkeypatch):
    objects = _objects()
    capsule = _CAPTURE(*objects)

    def trap(*args, **kwargs):
        raise AssertionError("function callback")

    with monkeypatch.context() as patch:
        patch.setattr(SolveExecutionControl.is_cancelled, "__code__", trap.__code__)
        _reject(objects)
        _reject(objects, capsule)


def test_original_contextmanager_generator_closure_cannot_be_rebound():
    objects = _objects()
    capsule = _CAPTURE(*objects)
    function = RSILearningController._python_admission_brs_observations
    cell = function.__closure__[0]
    original = cell.cell_contents
    cell.cell_contents = lambda *args, **kwargs: None
    try:
        _reject(objects)
        _reject(objects, capsule)
    finally:
        cell.cell_contents = original


@pytest.mark.parametrize("owner,name", [
    (_thread, "RLock"), (_thread, "get_ident"),
    (threading, "RLock"), (threading, "_CRLock"), (threading, "get_ident"),
    (locks.controller_module, "RSILearningController"),
    (locks.ledger_module, "RSILedger"), (locks.control_module, "SolveExecutionControl"),
])
def test_canonical_type_and_runtime_aliases_cannot_be_replaced(monkeypatch, owner, name):
    objects = _objects()
    capsule = _CAPTURE(*objects)
    with monkeypatch.context() as patch:
        patch.setattr(owner, name, object())
        _reject(objects)
        _reject(objects, capsule)


@pytest.mark.parametrize("name", ["type", "len", "vars", "any", "enumerate", "int", "super"])
def test_mutated_builtin_is_rejected_without_executing_it(name):
    objects = _objects()
    capsule = _CAPTURE(*objects)
    original = getattr(builtins, name)
    calls, errors = [], []

    def trap(*args, **kwargs):
        calls.append(1)
        raise AssertionError("builtin callback")

    setattr(builtins, name, trap)
    try:
        for action in (lambda: _CAPTURE(*objects), lambda: _ASSERT(*objects, capsule)):
            try:
                action()
            except RSILearningError as error:
                errors.append(error)
    finally:
        setattr(builtins, name, original)
    assert len(errors) == 2 and calls == []
    assert all(error.code == str(error) for error in errors)


@pytest.mark.parametrize("mapping", [vars(locks), vars(threading), vars(locks.controller_module),
                                     RSILedger.controller_lock_held.__dict__])
def test_foreign_guard_mapping_keys_refuse_before_callback_lookups(mapping):
    objects = _objects()
    capsule = _CAPTURE(*objects)
    key = _EvilKey("RLock")
    missing = object()
    original = mapping.pop("RLock", missing)
    mapping[key] = object()
    try:
        _reject(objects)
        _reject(objects, capsule)
    finally:
        del mapping[key]
        if original is not missing:
            mapping["RLock"] = original
    assert key.calls == 0


def test_module_registry_replacement_is_rejected(monkeypatch):
    objects = _objects()
    capsule = _CAPTURE(*objects)
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, locks.controller_module.__name__, types.ModuleType("foreign"))
        _reject(objects)
        _reject(objects, capsule)


def test_checker_code_is_pinned_before_execution(monkeypatch):
    objects = _objects()
    capsule = _CAPTURE(*objects)
    runtime = dict(zip(_CAPTURE.__code__.co_freevars,
                       (cell.cell_contents for cell in _CAPTURE.__closure__)))["runtime"]

    def trap():
        raise AssertionError("checker callback")

    code = runtime.__code__.replace(co_code=trap.__code__.co_code,
                                   co_consts=trap.__code__.co_consts,
                                   co_names=trap.__code__.co_names)
    with monkeypatch.context() as patch:
        patch.setattr(runtime, "__code__", code)
        _reject(objects)
        _reject(objects, capsule)


def test_refusal_never_invokes_a_changed_python_error_initializer(monkeypatch):
    objects = _objects()
    capsule = _CAPTURE(*objects)

    class ForeignError(Exception):
        def __init__(self, code):
            super().__init__("foreign callback")
            raise AssertionError("error initializer callback")

    trap = ForeignError.__init__
    initializer = RSILearningError.__init__
    assert len(initializer.__closure__) == len(trap.__closure__) == 1
    with monkeypatch.context() as patch:
        patch.setattr(initializer, "__code__", trap.__code__)
        _reject(objects)
        _reject(objects, capsule)


def test_error_factory_helper_is_pinned_before_any_python_invocation(monkeypatch):
    objects = _objects()
    capsule = _CAPTURE(*objects)
    factory = dict(zip(_CAPTURE.__code__.co_freevars,
                       (cell.cell_contents for cell in _CAPTURE.__closure__)))["make_error"]

    def trap():
        raise AssertionError("error factory callback")

    code = factory.__code__.replace(co_code=trap.__code__.co_code,
                                   co_consts=trap.__code__.co_consts,
                                   co_names=trap.__code__.co_names)
    with monkeypatch.context() as patch:
        patch.setattr(factory, "__code__", code)
        _reject(objects)
        _reject(objects, capsule)
