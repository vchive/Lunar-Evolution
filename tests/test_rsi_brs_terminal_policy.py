"""Finite terminal runtime dependencies must participate in the persisted policy."""
from __future__ import annotations

import re
import threading
from concurrent.futures import Future, ThreadPoolExecutor

import pytest

from lunar_evolution import rsi_brs_terminal_evidence as composer
from lunar_evolution import rsi_python_brs_terminal_lifecycle as terminal
from lunar_evolution.rsi_brs_publication_lineage import _policy
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
])
def test_terminal_runtime_method_replacement_invalidates_policy(monkeypatch, original_policy, target, name):
    monkeypatch.setattr(target, name, _replacement)
    _assert_drift(original_policy)


@pytest.mark.parametrize("module", [terminal, composer], ids=["worker-lifecycle", "terminal-composer"])
def test_regex_flag_change_with_identical_pattern_invalidates_policy(monkeypatch, original_policy, module):
    original = module._SHA
    changed = re.compile(original.pattern, original.flags | re.IGNORECASE)
    assert changed.pattern == original.pattern and changed.flags != original.flags
    monkeypatch.setattr(module, "_SHA", changed)
    _assert_drift(original_policy)
