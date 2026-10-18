"""Finite terminal runtime dependencies must participate in the persisted policy."""
from __future__ import annotations

import re
import threading
from concurrent.futures import Future, ThreadPoolExecutor

import pytest

from lunar_evolution import rsi_brs_terminal_evidence as composer
from lunar_evolution import rsi_python_brs_admission as admission
from lunar_evolution import rsi_python_brs_terminal_lifecycle as terminal
from lunar_evolution.rsi_brs_publication_lineage import _policy
from lunar_evolution.rsi_controller import RSILearningController
from lunar_evolution.rsi_learning import RSILearningError


@pytest.fixture(scope="module")
def original_policy():
    return _policy()


def _assert_drift(original):
    try:
        observed = _policy()
    except RSILearningError:
        return
    assert observed != original, "runtime dependency changed without invalidating the original policy"


def _replacement(*_args, **_kwargs):
    raise AssertionError("policy fingerprinting must not execute a substituted runtime dependency")


@pytest.mark.parametrize("target,name", [
    (Future, "done"),
    (Future, "running"),
    (Future, "exception"),
    (Future, "result"),
    (ThreadPoolExecutor, "shutdown"),
    (threading.Thread, "is_alive"),
    (threading, "current_thread"),
    (threading.Condition, "wait"),
    (threading.Condition, "notify_all"),
    (threading.Condition, "__enter__"),
    (threading.Condition, "__exit__"),
    (threading, "get_ident"),
    (RSILearningController, "_reconcile_brs_terminal_locked"),
])
def test_terminal_runtime_method_replacement_invalidates_policy(monkeypatch, original_policy, target, name):
    monkeypatch.setattr(target, name, _replacement)
    _assert_drift(original_policy)


@pytest.mark.parametrize("name", ["BRSAdmissionAck", "BRSAdmissionChannel", "build_brs_admission_ready"])
def test_terminal_admission_alias_replacement_refuses_before_runtime(monkeypatch, original_policy, name):
    monkeypatch.setattr(terminal, name, _replacement)
    with pytest.raises(RSILearningError, match="^rsi_brs_publication_lineage_native_reader_binding_drift$"):
        _policy()


def test_canonical_admission_ready_code_change_invalidates_policy(monkeypatch, original_policy):
    builder = admission.build_brs_admission_ready

    def changed(run_id, episode_id, payload):
        raise AssertionError("policy fingerprinting must not execute the changed ready builder")

    monkeypatch.setattr(builder, "__code__", changed.__code__)
    assert terminal.build_brs_admission_ready is builder
    _assert_drift(original_policy)


@pytest.mark.parametrize("module", [terminal, composer], ids=["worker-lifecycle", "terminal-composer"])
def test_regex_flag_change_with_identical_pattern_invalidates_policy(monkeypatch, original_policy, module):
    original = module._SHA
    changed = re.compile(original.pattern, original.flags | re.IGNORECASE)
    assert changed.pattern == original.pattern and changed.flags != original.flags
    monkeypatch.setattr(module, "_SHA", changed)
    _assert_drift(original_policy)
