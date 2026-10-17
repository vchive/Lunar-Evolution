"""Real local Condition objects, without owner/ACK or worker authority."""

from __future__ import annotations

import _thread
import builtins
import sys
import threading
import types
from collections import deque

import pytest

from lunar_evolution import rsi_brs_rejection_ready_sync as sync
from lunar_evolution.rsi_learning import RSILearningError

_CAPTURE = sync.capture_ready_condition
_ASSERT = sync.assert_ready_condition
_ERROR = "rsi_brs_rejection_ready_sync_"


def _reject(condition, snapshot=None):
    with pytest.raises(RSILearningError, match=_ERROR):
        if snapshot is None:
            _CAPTURE(condition)
        else:
            _ASSERT(condition, snapshot)


@pytest.mark.parametrize("locked", [False, True])
def test_original_custody_outside_and_inside_native_context(locked):
    condition = threading.Condition()
    snapshot = _CAPTURE(condition)
    assert type(snapshot) is tuple and len(snapshot) == 8
    assert snapshot[:3] == (condition, condition._lock, condition._waiters)
    if locked:
        with snapshot[1]:
            _ASSERT(condition, snapshot)
    else:
        _ASSERT(condition, snapshot)
    assert not condition._is_owned()


def test_real_waiter_can_arrive_and_leave_without_freezing_deque_contents():
    condition = threading.Condition()
    snapshot = _CAPTURE(condition)
    entering = threading.Event()
    finished = threading.Event()

    def wait():
        with condition:
            entering.set()
            condition.wait(timeout=3)
        finished.set()

    worker = threading.Thread(target=wait)
    worker.start()
    try:
        assert entering.wait(timeout=3)
        with snapshot[1]:
            assert len(condition._waiters) == 1
            assert type(condition._waiters[0]) is _thread.LockType
            _ASSERT(condition, snapshot)
            condition.notify_all()
        assert finished.wait(timeout=3)
        _ASSERT(condition, snapshot)
        assert len(condition._waiters) == 0
    finally:
        with snapshot[1]:
            condition.notify_all()
        worker.join(timeout=4)
    assert not worker.is_alive()


@pytest.mark.parametrize("factory", [
    lambda: object(), lambda: type("ForeignCondition", (threading.Condition,), {})(),
    lambda: threading.Condition(_thread.allocate_lock()),
])
def test_reject_foreign_condition_and_nonrecursive_lock(factory):
    _reject(factory())


@pytest.mark.parametrize("name", [
    "wait", "notify", "notify_all", "__enter__", "__exit__", "_is_owned", "_release_save",
    "_acquire_restore", "acquire", "release", "unknown",
])
def test_reject_instance_shadow_before_executing_callback(name):
    condition = threading.Condition()
    snapshot = _CAPTURE(condition)
    calls = []

    def trap(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("foreign callback")

    setattr(condition, name, trap)
    _reject(condition)
    _reject(condition, snapshot)
    assert calls == []


@pytest.mark.parametrize("name", ["_lock", "_waiters"])
def test_equal_kind_original_container_replacement_breaks_custody(name):
    condition = threading.Condition()
    snapshot = _CAPTURE(condition)
    if name == "_lock":
        lock = threading.RLock()
        condition._lock = lock
        for field in ("acquire", "release", "_release_save", "_acquire_restore", "_is_owned"):
            setattr(condition, field, getattr(lock, field))
    else:
        condition._waiters = deque()
    _reject(condition, snapshot)


@pytest.mark.parametrize("name", [
    "acquire", "release", "_release_save", "_acquire_restore", "_is_owned",
])
def test_reconstructed_native_wrapper_is_not_original_snapshot_operation(name):
    condition = threading.Condition()
    snapshot = _CAPTURE(condition)
    replacement = getattr(condition._lock, name)
    assert replacement is not getattr(condition, name)
    setattr(condition, name, replacement)
    _reject(condition, snapshot)


def test_operation_from_different_lock_rejected_even_before_capture():
    condition = threading.Condition()
    condition.acquire = threading.RLock().acquire
    _reject(condition)


@pytest.mark.parametrize("waiters", [
    deque(maxlen=0), deque(maxlen=2), deque([object()]), deque([threading.RLock()]),
    deque([_thread.allocate_lock()] * 2), deque(_thread.allocate_lock() for _ in range(4097)),
    [],
])
def test_bounded_exact_waiter_domain(waiters):
    condition = threading.Condition()
    condition._waiters = waiters
    _reject(condition)


def test_maximum_distinct_native_waiters_and_natural_contents_changes_are_allowed():
    condition = threading.Condition()
    condition._waiters.extend(_thread.allocate_lock() for _ in range(4096))
    snapshot = _CAPTURE(condition)
    condition._waiters.clear()
    condition._waiters.append(_thread.allocate_lock())
    _ASSERT(condition, snapshot)


@pytest.mark.parametrize("snapshot", [[], (), (None,) * 7, (None,) * 8, (None,) * 9])
def test_snapshot_domain(snapshot):
    _reject(threading.Condition(), snapshot)


def test_snapshot_for_foreign_condition_is_not_authority():
    condition = threading.Condition()
    _reject(threading.Condition(), _CAPTURE(condition))


class _EvilKey:
    def __init__(self):
        self.calls = 0

    def __hash__(self):
        return hash("_lock")

    def __eq__(self, other):
        self.calls += 1
        raise AssertionError("key equality callback")


def test_instance_keys_are_validated_before_lookups_and_comparisons():
    condition = threading.Condition()
    key = _EvilKey()
    del condition.__dict__["_lock"]
    condition.__dict__[key] = object()
    _reject(condition)
    assert key.calls == 0


@pytest.mark.parametrize("name", [
    "__enter__", "__exit__", "wait", "notify", "notify_all", "__init__",
    "_release_save", "_acquire_restore", "_is_owned", "__getattribute__", "__getattr__",
])
def test_class_replacement_or_new_magic_is_rejected_before_capture(monkeypatch, name):
    condition = threading.Condition()
    snapshot = _CAPTURE(condition)
    calls = []

    def trap(*args, **kwargs):
        calls.append(1)
        raise AssertionError("class callback")

    with monkeypatch.context() as patch:
        patch.setattr(threading.Condition, name, trap, raising=False)
        _reject(condition)
        _reject(condition, snapshot)
    assert calls == []


@pytest.mark.parametrize("name", ["wait", "notify", "notify_all", "__enter__", "__exit__"])
def test_live_function_code_drift_is_rejected_without_execution(monkeypatch, name):
    condition = threading.Condition()
    snapshot = _CAPTURE(condition)
    function = vars(threading.Condition)[name]
    calls = []

    def trap(self, *args, **kwargs):
        raise AssertionError("live code executed")

    with monkeypatch.context() as patch:
        patch.setattr(function, "__code__", trap.__code__)
        _reject(condition)
        _reject(condition, snapshot)
    assert calls == []


@pytest.mark.parametrize("attribute,replacement", [
    ("__defaults__", (99,)), ("__kwdefaults__", {"foreign": 1}),
    ("__dict__", {"foreign": 1}), ("__annotations__", {"foreign": int}),
    ("__name__", "foreign"), ("__qualname__", "foreign"),
    ("__module__", "foreign"), ("__doc__", "foreign"),
])
def test_function_mutable_fields_are_pinned(monkeypatch, attribute, replacement):
    condition = threading.Condition()
    snapshot = _CAPTURE(condition)
    with monkeypatch.context() as patch:
        patch.setattr(threading.Condition.wait, attribute, replacement)
        _reject(condition)
        _reject(condition, snapshot)


@pytest.mark.parametrize("owner,name", [
    (threading, "Condition"), (threading, "RLock"), (threading, "_CRLock"),
    (threading, "_allocate_lock"), (threading, "_deque"), (threading, "_islice"),
    (_thread, "RLock"), (_thread, "LockType"), (_thread, "allocate_lock"),
])
def test_independent_module_aliases_cannot_be_replaced(monkeypatch, owner, name):
    condition = threading.Condition()
    snapshot = _CAPTURE(condition)
    with monkeypatch.context() as patch:
        patch.setattr(owner, name, object())
        _reject(condition)
        _reject(condition, snapshot)


def test_matching_fake_canonical_and_threading_aliases_still_fail(monkeypatch):
    condition = threading.Condition()
    with monkeypatch.context() as patch:
        foreign = lambda: None
        patch.setattr(_thread, "allocate_lock", foreign)
        patch.setattr(threading, "_allocate_lock", foreign)
        _reject(condition)


@pytest.mark.parametrize("name", ["len", "RuntimeError", "ValueError", "AttributeError"])
def test_threading_global_cannot_shadow_builtin(monkeypatch, name):
    condition = threading.Condition()
    snapshot = _CAPTURE(condition)
    calls = []

    def trap(*args, **kwargs):
        calls.append(1)
        raise AssertionError("global shadow executed")

    with monkeypatch.context() as patch:
        patch.setattr(threading, name, trap, raising=False)
        _reject(condition)
        _reject(condition, snapshot)
    assert calls == []


@pytest.mark.parametrize("name", ["any", "len", "vars", "type"])
def test_mutated_builtin_does_not_execute_before_rejection(name):
    condition = threading.Condition()
    snapshot = _CAPTURE(condition)
    original = getattr(builtins, name)
    calls = []
    errors = []

    def trap(*args, **kwargs):
        calls.append(1)
        raise AssertionError("builtin callback")

    # Do not run pytest internals while process-wide builtins are patched.
    setattr(builtins, name, trap)
    try:
        for action in (lambda: _CAPTURE(condition), lambda: _ASSERT(condition, snapshot)):
            try:
                action()
            except RSILearningError as error:
                errors.append(error)
    finally:
        setattr(builtins, name, original)
    assert len(errors) == 2
    assert calls == []


@pytest.mark.parametrize("name", ["sys", "builtins", "threading"])
def test_guard_module_alias_rejected_without_foreign_attribute_access(monkeypatch, name):
    condition = threading.Condition()
    snapshot = _CAPTURE(condition)
    calls = []

    class Foreign:
        def __getattribute__(self, name):
            calls.append(name)
            raise AssertionError("module callback")

    with monkeypatch.context() as patch:
        patch.setattr(sync, name, Foreign())
        _reject(condition)
        _reject(condition, snapshot)
    assert calls == []


def test_module_registry_replacement_rejected(monkeypatch):
    condition = threading.Condition()
    snapshot = _CAPTURE(condition)
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, "threading", types.ModuleType("threading"))
        _reject(condition)
        _reject(condition, snapshot)


def test_guard_runtime_live_code_is_rejected_before_execution(monkeypatch):
    condition = threading.Condition()
    snapshot = _CAPTURE(condition)
    runtime = dict(zip(_CAPTURE.__code__.co_freevars,
                       (cell.cell_contents for cell in _CAPTURE.__closure__)))['runtime']

    def trap():
        raise AssertionError("checker code executed")

    # Replacing a closure function requires code with the same freevar count.
    code = runtime.__code__.replace(co_code=trap.__code__.co_code,
                                   co_consts=trap.__code__.co_consts,
                                   co_names=trap.__code__.co_names)
    with monkeypatch.context() as patch:
        patch.setattr(runtime, "__code__", code)
        _reject(condition)
        _reject(condition, snapshot)


def test_native_lock_and_deque_subclasses_are_rejected():
    class RLockSubclass(_thread.RLock):
        pass

    class DequeSubclass(deque):
        pass

    for condition in (threading.Condition(RLockSubclass()), threading.Condition()):
        if type(condition._lock) is _thread.RLock:
            condition._waiters = DequeSubclass()
        _reject(condition)


def test_tuple_subclass_snapshot_is_rejected():
    class TupleSubclass(tuple):
        pass

    condition = threading.Condition()
    _reject(condition, TupleSubclass(_CAPTURE(condition)))


@pytest.mark.parametrize("target", ["function_attributes", "threading_namespace", "guard_namespace"])
def test_nonstring_keys_rejected_before_callback_lookups(target):
    condition = threading.Condition()
    snapshot = _CAPTURE(condition)
    key = _EvilKey()
    mapping = {"function_attributes": threading.Condition.wait.__dict__,
               "threading_namespace": vars(threading), "guard_namespace": vars(sync)}[target]
    mapping[key] = object()
    try:
        _reject(condition)
        _reject(condition, snapshot)
    finally:
        del mapping[key]
    assert key.calls == 0


def test_module_namespace_is_bounded(monkeypatch):
    condition = threading.Condition()
    snapshot = _CAPTURE(condition)
    with monkeypatch.context() as patch:
        for index in range(16385):
            patch.setattr(threading, f"ready_sync_bound_{index}", None, raising=False)
        _reject(condition)
        _reject(condition, snapshot)
